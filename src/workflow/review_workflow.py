"""workflows/review_workflow.py：LangGraph 编排层，把已经验证过的各模块串成一张图。

State、Node、Edge 的设计已经在之前的讨论中确认，本文件只是把确认过的设计
落成代码，不在这里重新做设计决策。

节点对应的真实业务函数：
    Contract Loading → document.preparation.parse_and_split_contract（Capability，见下）
    LLM Review        → agents.review_agent.ClauseReviewer.review（逐条调用）
    Rule Check        → rules.RuleChecker.check
    Merge              → rules.merge_review_results
    Report Assembly   → schemas.ReviewReport 构造

图结构（7 条边，全部是普通边，没有条件边）：
    START → Contract Loading
    Contract Loading → LLM Review
    Contract Loading → Rule Check
    LLM Review → Merge
    Rule Check → Merge
    Merge → Report Assembly
    Report Assembly → END

依赖边界说明（Stage 2 调整）：解析 + 切分的编排函数（parse_contract /
split_contract / parse_and_split_contract）已经从本文件搬到
document/preparation.py——它们不是"审查流程"本身的一部分，而是一段
三处共用的合同加载能力（Review Workflow 的 Contract Loading 节点、
ModificationService.generate_v2、api/routes/contracts.py 的 POST /parse
都要用），继续放在本文件里会让 Review Workflow 变成"其他模块伸手进来拿
工具函数的地方"，这不是 Workflow 该扮演的角色。本文件现在只从
document.preparation 导入这组函数来用，不再是它们的实现者或唯一入口。

ContractManager、RuleChecker、agents.review_agent 仍然是本文件会引用到的
模块（通过 build_graph() 的参数注入），这条既有边界没有变。

本阶段明确的架构决策（不是遗漏，已经讨论并记录过）：
    - Contract Loading / Rule Check / Merge / Report Assembly 任何一个抛出
      异常，直接终止整张图的执行，不做统一 error state、不做条件分支、
      不做重试/降级。
    - 只有 LLM Review 对单条 Clause 的 ReviewError 会被捕获，计入
      failed_clauses，不会中止整张图，其余条款继续处理。
    - ReviewGraphState 只是图内部传递数据用的 TypedDict，不对外暴露——
      本文件唯一对外的入口是 run_review()，它的返回值是一个真正的业务对象
      ReviewReport，不是裸的 LangGraph state dict。外部任何模块（API、
      ModificationService 的 V2 复审等）都只应该拿到 ReviewReport，不应该
      再伸手去读 final_state["final_results"] 这类内部字段。
    - 图本身"跑完"这件事和"图跑完后怎么包装成业务对象"是两层关注点，所以
      拆成 run_review_graph（内部，返回 ReviewGraphState，供本文件和白盒
      测试使用）+ run_review（对外，返回 ReviewReport）两个函数，而不是在
      一个函数里把两件事混在一起。

本次修正（见 docs/PITFALLS.md 对应日期的记录）：之前 report_assembly 节点
只是"构造一次 ReviewReport 用来验证能不能构造出来"，构造结果被直接丢弃，
真正对外返回的 ReviewReport 是 run_review() 在图跑完之后、图外部重新拼一次
——这意味着"这一次审查最终的报告"实际上有两份构造逻辑（图内一份、图外一份），
只是看起来一致，一旦其中一处字段计算方式调整，两处就可能悄悄分叉。现在
ReviewGraphState 新增 report 字段，report_assembly 节点构造的就是最终要
对外返回的 ReviewReport 本体，并通过 `return {"report": report}` 写回
state；run_review() 只从 final_state["report"] 里取出这个对象直接返回，
不再在图外重新构造。
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from domain.agents.review_agent import ClauseReviewer, ReviewError
from infra.storage import ContractManager
from domain.document.preparation import parse_and_split_contract
from domain.rules import RuleChecker, merge_review_results
from core import Clause, FailedClause, ReviewReport, ReviewResult, ReviewVersions


class ReviewGraphState(TypedDict):
    contract_id: str
    clauses: list[Clause]

    llm_results: list[ReviewResult]
    rule_results: list[ReviewResult]
    final_results: list[ReviewResult]

    failed_clauses: list[FailedClause]

    # 图跑完后的最终业务对象，只由 report_assembly 节点写入一次；run_review()
    # 直接从这里取值返回，不再在图外重新构造同样的 ReviewReport。
    report: Optional[ReviewReport]


def build_graph(
    contract_manager: ContractManager,
    reviewer: ClauseReviewer,
    rule_checker: RuleChecker,
):
    """组装 5 个 Node + 7 条边，返回编译好的图。

    contract_manager / reviewer / rule_checker 是已经构造好的基础设施实例，
    通过闭包注入到各节点里；本函数不负责构造它们（不知道怎么连 BGE-M3、
    DeepSeek、Chroma——那是调用方的事，目前只有 scripts/ 里的验证脚本会做）。
    """

    def contract_loading(state: ReviewGraphState) -> dict:
        contract_id = state["contract_id"]
        clauses = parse_and_split_contract(contract_id, contract_manager)
        return {"clauses": clauses}

    def llm_review(state: ReviewGraphState) -> dict:
        llm_results: list[ReviewResult] = []
        failed_clauses: list[FailedClause] = []
        for clause in state["clauses"]:
            try:
                llm_results.append(reviewer.review(clause))
            except ReviewError as exc:
                failed_clauses.append(FailedClause(clause_id=clause.clause_id, error=str(exc)))
        return {"llm_results": llm_results, "failed_clauses": failed_clauses}

    def rule_check(state: ReviewGraphState) -> dict:
        rule_results = rule_checker.check(state["clauses"])
        return {"rule_results": rule_results}

    def merge(state: ReviewGraphState) -> dict:
        final_results = merge_review_results(state["llm_results"], state["rule_results"])
        return {"final_results": final_results}

    def report_assembly(state: ReviewGraphState) -> dict:
        """构造这一次审查最终要对外返回的 ReviewReport，并写回 state["report"]。

        这是全流程唯一一处构造最终 ReviewReport 的地方——run_review() 不会
        再重新构造一次，只会把这里产出的对象原样返回。
        """
        report = ReviewReport(
            contract_id=state["contract_id"],
            results=state["final_results"],
            failed_clauses=state["failed_clauses"],
            versions=ReviewVersions(),
        )
        return {"report": report}

    graph = StateGraph(ReviewGraphState)
    graph.add_node("contract_loading", contract_loading)
    graph.add_node("llm_review", llm_review)
    graph.add_node("rule_check", rule_check)
    graph.add_node("merge", merge)
    graph.add_node("report_assembly", report_assembly)

    graph.add_edge(START, "contract_loading")
    graph.add_edge("contract_loading", "llm_review")
    graph.add_edge("contract_loading", "rule_check")
    graph.add_edge("llm_review", "merge")
    graph.add_edge("rule_check", "merge")
    graph.add_edge("merge", "report_assembly")
    graph.add_edge("report_assembly", END)

    return graph.compile()


def run_review_graph(
    contract_id: str,
    contract_manager: ContractManager,
    reviewer: ClauseReviewer,
    rule_checker: RuleChecker,
) -> ReviewGraphState:
    """构建图、编译、跑一次完整审查，返回最终 State。

    这是图跑完后的"原始"结果，只在本文件内部（run_review）和白盒测试
    （验证 State 字段、并行分支是否真的并行执行等图结构本身的细节）里使用。
    本文件之外的业务代码不应该直接调用这个函数——它们应该调用 run_review()，
    拿到的是 ReviewReport，而不是这个内部 TypedDict。
    """
    compiled_graph = build_graph(contract_manager, reviewer, rule_checker)
    initial_state: ReviewGraphState = {
        "contract_id": contract_id,
        "clauses": [],
        "llm_results": [],
        "rule_results": [],
        "final_results": [],
        "failed_clauses": [],
        "report": None,
    }
    return compiled_graph.invoke(initial_state)


def run_review(
    contract_id: str,
    contract_manager: ContractManager,
    reviewer: ClauseReviewer,
    rule_checker: RuleChecker,
) -> ReviewReport:
    """对外的唯一入口：跑一次完整审查，返回 ReviewReport 业务对象。

    本文件之外的任何模块（API 路由、app/review_service.py、
    ModificationService 对 V2 的复审……）都应该调用这个函数，而不是
    run_review_graph——这样"图的最终 state 长什么样"永远是本文件内部的
    实现细节，可以随时调整，不会波及调用方。

    本函数不做持久化（不调用 ContractManager.save_review）——是否保存、
    保存成什么版本号，是 app/review_service.py 的职责，不是
    Review Workflow 的职责，这里保持纯粹的"跑一次审查、返回报告"。
    """
    final_state = run_review_graph(contract_id, contract_manager, reviewer, rule_checker)
    report = final_state["report"]
    assert report is not None  # report_assembly 节点必定会写入这个字段
    return report
