"""review/pipeline.py 的 LangGraph 流程测试。

LangGraph 使用真实安装的 langgraph 包，不使用任何 LangGraph 替身。
外部服务（RAG 检索、DeepSeek）用假对象注入，其余全部是真实实现：
ContractManager / DocumentParser / ClauseSplitter / ClauseReviewer / RuleChecker / merge。

用一份 3 条款的合同（写入真实临时文件）：
    clause_001 合同期限：一年
    clause_002 试用期：三个月、试用期工资为正式工资的 50%
    clause_003 保密义务
RuleChecker 会命中两条规则：
    probation_salary_below_80_percent   → clause_002
    probation_duration_exceeds_legal_cap → related = [clause_001, clause_002]
"""

import pytest

from domain.agents.review_agent import ClauseReviewer
from infra.storage import ContractManager, ContractNotFoundError
from infra.llm import LLMClientError
from domain.rules import RuleChecker
from core import Evidence, ReviewReport, ReviewSource
from workflow.review_workflow import ReviewGraphState, run_review, run_review_graph

CONTRACT_TEXT = (
    "第一条 合同期限\n"
    "本合同期限为一年。\n\n"
    "第二条 试用期\n"
    "乙方试用期为三个月，试用期工资为正式工资标准的百分之五十。\n\n"
    "第三条 保密义务\n"
    "乙方应对甲方商业秘密予以保密。\n"
)

# Stage 2 的 Report Assembly 修复：report_assembly 节点现在真正把最终
# ReviewReport 写回 State（见 workflows/review_workflow.py），run_review()
# 直接从最终 state 取 "report" 返回，不再在 Graph 外重新组装一遍——所以
# "report" 从这里开始正式成为锁定字段之一，不是遗漏。
LOCKED_STATE_FIELDS = {
    "contract_id",
    "clauses",
    "llm_results",
    "rule_results",
    "final_results",
    "failed_clauses",
    "report",
}

NO_RISK_JSON = '{"risk": false, "risk_level": "none", "reason": "示例：未发现风险", "legal_basis": [], "suggestion": ""}'


# ---------------------------------------------------------------- 测试替身（仅外部服务）

class FakeRetriever:
    def search_legal_knowledge(self, query, k=None):
        return [Evidence(content="示例法条内容", source="劳动合同法", article="第十七条", metadata={"score": 0.1})]


class FakeLLMClient:
    """按条款内容决定成败，与调用顺序无关：
    fail_on_keyword —— 用户消息包含该关键词的那条款调用失败；fail_always —— 全部失败。
    """

    model = "fake-model"

    def __init__(self, fail_on_keyword=None, fail_always=False):
        self.fail_on_keyword = fail_on_keyword
        self.fail_always = fail_always
        self.calls = 0

    def chat(self, messages, temperature=0.0, json_mode=False):
        self.calls += 1
        user_content = messages[-1]["content"]
        if self.fail_always or (self.fail_on_keyword and self.fail_on_keyword in user_content):
            raise LLMClientError("模拟的 LLM 调用失败")
        return NO_RISK_JSON


class SpyRuleChecker(RuleChecker):
    """真实的 RuleChecker，只额外记录每次 check() 收到的条款。"""

    def __init__(self):
        super().__init__()
        self.calls = []

    def check(self, clauses):
        self.calls.append([c.clause_id for c in clauses])
        return super().check(clauses)


class ExplodingRuleChecker:
    def check(self, clauses):
        raise RuntimeError("规则引擎内部错误")


# ---------------------------------------------------------------- 辅助

def make_contract(tmp_path):
    source = tmp_path / "contract.txt"
    source.write_text(CONTRACT_TEXT, encoding="utf-8")
    manager = ContractManager(root_dir=tmp_path / "contracts")
    return manager, manager.create_contract(source).contract_id


def make_reviewer(llm_client):
    return ClauseReviewer(FakeRetriever(), llm_client, top_k=3)


# ---------------------------------------------------------------- State 契约

def test_state_has_exactly_the_locked_fields():
    # 锁定的 State 设计：不含 report / error / evidence / versions 等其他字段
    assert set(ReviewGraphState.__annotations__) == LOCKED_STATE_FIELDS


def test_final_state_contains_all_locked_fields(tmp_path):
    manager, contract_id = make_contract(tmp_path)

    state = run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())

    assert LOCKED_STATE_FIELDS <= set(state)
    assert state["contract_id"] == contract_id


# ---------------------------------------------------------------- Contract Loading

def test_contract_loading_produces_clauses_in_state(tmp_path):
    manager, contract_id = make_contract(tmp_path)

    state = run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())

    assert [c.clause_id for c in state["clauses"]] == ["clause_001", "clause_002", "clause_003"]


# ---------------------------------------------------------------- 并行分支与汇合

def test_both_parallel_branches_execute(tmp_path):
    manager, contract_id = make_contract(tmp_path)
    llm_client = FakeLLMClient()
    rule_checker = SpyRuleChecker()

    run_review_graph(contract_id, manager, make_reviewer(llm_client), rule_checker)

    assert llm_client.calls == 3  # LLM 分支：逐条审查 3 个条款
    assert rule_checker.calls == [["clause_001", "clause_002", "clause_003"]]  # 规则分支：一次拿到全部条款


def test_branches_join_at_merge_without_overwriting(tmp_path):
    manager, contract_id = make_contract(tmp_path)

    state = run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())

    assert len(state["llm_results"]) == 3
    assert len(state["rule_results"]) == 2
    # 汇合：merge 必须同时拿到两个分支的结果；任何一个分支的结果都没有被覆盖或丢失
    assert len(state["final_results"]) == len(state["llm_results"]) + len(state["rule_results"]) == 5
    assert state["final_results"] == state["llm_results"] + state["rule_results"]
    assert {r.source for r in state["final_results"]} == {ReviewSource.LLM, ReviewSource.RULE}


def test_rule_hit_clause_keeps_both_llm_and_rule_results(tmp_path):
    manager, contract_id = make_contract(tmp_path)

    state = run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())

    sources_of_clause_002 = {r.source for r in state["final_results"] if r.clause_id == "clause_002"}
    assert sources_of_clause_002 == {ReviewSource.LLM, ReviewSource.RULE}


def test_rules_only_touch_the_clauses_they_apply_to(tmp_path):
    manager, contract_id = make_contract(tmp_path)

    state = run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())

    affected = {r.clause_id for r in state["rule_results"] if r.clause_id}
    affected |= {cid for r in state["rule_results"] for cid in r.related_clause_ids}
    assert affected == {"clause_001", "clause_002"}  # clause_003 不受规则影响


# ---------------------------------------------------------------- failed_clauses

def test_llm_failure_is_recorded_and_other_clauses_continue(tmp_path):
    manager, contract_id = make_contract(tmp_path)
    llm_client = FakeLLMClient(fail_on_keyword="商业秘密")  # 只让 clause_003 失败

    state = run_review_graph(contract_id, manager, make_reviewer(llm_client), RuleChecker())

    assert [f.clause_id for f in state["failed_clauses"]] == ["clause_003"]
    assert "clause_003" in state["failed_clauses"][0].error
    assert [r.clause_id for r in state["llm_results"]] == ["clause_001", "clause_002"]
    assert len(state["rule_results"]) == 2  # 规则分支不受 LLM 单条失败影响
    assert len(state["final_results"]) == 4  # 图正常跑完，没有中止


def test_rule_branch_is_independent_of_llm_branch(tmp_path):
    manager, contract_id = make_contract(tmp_path)
    llm_client = FakeLLMClient(fail_always=True)  # LLM 分支全军覆没

    state = run_review_graph(contract_id, manager, make_reviewer(llm_client), RuleChecker())

    assert state["llm_results"] == []
    assert len(state["failed_clauses"]) == 3
    assert len(state["rule_results"]) == 2
    assert state["final_results"] == state["rule_results"]


# ---------------------------------------------------------------- 异常向上抛出（已确认的架构决策）

def test_contract_loading_error_propagates_and_aborts_the_graph(tmp_path):
    manager, _ = make_contract(tmp_path)
    llm_client = FakeLLMClient()
    rule_checker = SpyRuleChecker()

    with pytest.raises(ContractNotFoundError):
        run_review_graph("this-contract-does-not-exist", manager, make_reviewer(llm_client), rule_checker)

    # 图被中止：两个下游分支都没有机会执行
    assert llm_client.calls == 0
    assert rule_checker.calls == []


def test_rule_check_error_propagates(tmp_path):
    manager, contract_id = make_contract(tmp_path)

    with pytest.raises(RuntimeError):
        run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), ExplodingRuleChecker())


# ---------------------------------------------------------------- Report Assembly / 对外契约

def test_report_assembly_node_writes_real_report_into_state(tmp_path):
    # Stage 2 修复：report_assembly 节点现在真正把组装好的 ReviewReport
    # 写回 State 的 "report" 字段，不再只是"构造一次验证能跑通就丢弃"——
    # 调用方（run_review）直接从这个字段取结果，不在 Graph 外重新拼一遍。
    manager, contract_id = make_contract(tmp_path)
    llm_client = FakeLLMClient(fail_on_keyword="商业秘密")

    state = run_review_graph(contract_id, manager, make_reviewer(llm_client), RuleChecker())

    assert set(state) == LOCKED_STATE_FIELDS
    assert isinstance(state["report"], ReviewReport)
    assert state["report"].contract_id == contract_id
    assert state["report"].results == state["final_results"]
    assert state["report"].failed_clauses == state["failed_clauses"]


# ---------------------------------------------------------------- 对外入口：run_review 返回 ReviewReport

def test_run_review_returns_a_review_report_not_a_bare_state(tmp_path):
    """Stage 2 调整：run_review 对外的返回值必须是 ReviewReport 业务对象，
    不是裸的 LangGraph state dict——调用方（API、app/review_service.py、
    ModificationService 的 V2 复审）不应该再伸手去读 final_state["final_results"]。
    """
    manager, contract_id = make_contract(tmp_path)
    llm_client = FakeLLMClient(fail_on_keyword="商业秘密")

    report = run_review(contract_id, manager, make_reviewer(llm_client), RuleChecker())

    assert isinstance(report, ReviewReport)
    assert report.contract_id == contract_id
    assert len(report.results) == 4
    assert [f.clause_id for f in report.failed_clauses] == ["clause_003"]
    assert report.overall_risk_level.value == "high"  # 规则命中的两条都是 high


def test_run_review_report_matches_run_review_graph_final_state(tmp_path):
    """run_review 不是另一套独立实现，只是把 run_review_graph 的最终 state
    包装成 ReviewReport——两者在同一份合同上应该得到完全一致的结果。
    """
    manager, contract_id = make_contract(tmp_path)

    state = run_review_graph(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())
    report = run_review(contract_id, manager, make_reviewer(FakeLLMClient()), RuleChecker())

    assert report.contract_id == state["contract_id"]
    assert report.results == state["final_results"]
    assert report.failed_clauses == state["failed_clauses"]


def test_run_review_propagates_contract_loading_error_same_as_graph(tmp_path):
    manager, _ = make_contract(tmp_path)

    with pytest.raises(ContractNotFoundError):
        run_review("this-contract-does-not-exist", manager, make_reviewer(FakeLLMClient()), RuleChecker())
