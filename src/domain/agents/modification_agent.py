"""ModificationAgent：合同修改工作流里"决定怎么改"的那一步。

和 domain/agents/review_agent.py 的 ClauseReviewer 是同一种角色定位（单一职责、不做
编排），但服务的是完全不同的业务目标，所以故意不合并、不复用同一个类：
    ClauseReviewer     —— 审查 Agent：判断条款有没有风险。
    ModificationAgent  —— 修改 Agent：在律师明确要求下，生成条款的修改文本。

Agent 和普通 LLM 调用的区别，在这里具体体现为：
    普通调用：把 messages 丢给 LLM，拿到一段自由文本，自己再想办法解析。
    Agent（本模块）：明确告诉模型"你只有一个工具 modify_clause，只能通过
    调用它来给出结果"，由 LLM 自己决定要不要调用、怎么填参数——决定权在
    模型，不在这段 Python 代码里的 if/else。第一版只有一个工具，所以看起来
    像是"总会调用"，但机制上是真正的 Function Calling，不是把 JSON 硬解析
    伪装成 Agent。

本模块不做的事（有意省略）：
    - 不做多工具的自主选择（第一版只有一个工具）
    - 不做检索（如果 Prompt 需要法律依据，直接复用传入的 review_result.legal_basis，
      不重新调用 RAG——修改阶段不需要，也不应该重新触发一次检索）
    - 不做重试策略（重试次数、"基于原文而不是上一次候选重新生成"这些策略
      属于编排层 modification/service.py，不属于 Agent 本身）

依赖边界：只依赖 domain.ports.LLMPort、domain.prompts.modification、
domain.modification.tool、core；不依赖 workflow/*、不依赖 infra。
"""

from typing import Optional, Union

from domain.ports import LLMPort, LLMPortError
from domain.modification.tool import ModificationToolError, execute_modify_clause
from domain.prompts.modification import MODIFY_CLAUSE_TOOL_SCHEMA, build_modification_messages
from core import Clause, ModificationResult, ReviewResult, ReviewResultSnapshot


class ModificationAgentError(Exception):
    """Modification Agent 生成候选失败（LLM 调用失败、工具参数不合法、越界修改等）。

    不做静默兜底：出问题就抛出来，由 modification/service.py 决定怎么记录
    这次失败的尝试。
    """


class ModificationAgent:
    """针对单个条款的修改 Agent：拼 Prompt → Function Calling → 解析工具调用。"""

    def __init__(self, llm_client: LLMPort) -> None:
        self.llm_client = llm_client

    def generate_candidate(
        self,
        clause: Clause,
        review_result: Optional[Union[ReviewResult, ReviewResultSnapshot]],
        lawyer_instructions: list[str],
    ) -> ModificationResult:
        """生成一轮候选修改结果。

        lawyer_instructions 是【全部历史意见】，且 clause 永远是 V1 的原始条款
        ——调用方（service 层）负责保证"每一轮都基于原始条款重新生成"，本方法
        本身不知道、也不需要知道这是第几轮重试。

        review_result 现在传入的是 ModificationTask.source_review_snapshot
        （创建任务时冻结的快照），不是"当前最新一次审查"——两者共享
        risk_level/reason/legal_basis/suggestion 这几个字段名，
        build_modification_messages 只按属性读取，接受任意一种都能正常工作。
        """
        messages = build_modification_messages(clause, review_result, lawyer_instructions)

        try:
            arguments = self.llm_client.chat_with_tool(messages, MODIFY_CLAUSE_TOOL_SCHEMA)
        except LLMPortError as exc:
            raise ModificationAgentError(f"调用 LLM 失败（clause_id={clause.clause_id}）：{exc}") from exc

        try:
            return execute_modify_clause(expected_clause_id=clause.clause_id, arguments=arguments)
        except ModificationToolError as exc:
            raise ModificationAgentError(str(exc)) from exc
