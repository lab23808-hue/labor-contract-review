"""QAApplicationService：最小化的自然语言问答能力（Part J）。

明确不是什么（范围纪律）：
    - 不是 LangGraph / Agent / Tool-Calling 系统——没有多轮规划、没有工具
      自主选择，流程只有三步：收集数据 → 拼一个 Prompt → 调用一次 LLM。
    - 不新建任何 RAG 索引——不检索法律知识库，只读取这份合同自己已经产生
      的数据（Contract 元数据、Clause、ReviewResult、ModificationTask/
      ModificationAttempt、ContractVersion 关联的 V2 数据）。
    - 不做多轮对话记忆——每次提问都是一次独立的"收集数据 + 问答"，不维护
      会话历史（如果以后需要多轮上下文，应该是调用方自己拼接问题文本，
      不应该让本服务反过来长出状态）。

数据收集范围：Contract 元数据、顶层 Clause 概览、最近一次 ReviewResult、
全部 ModificationTask + 其 ModificationAttempt、该合同的 ContractVersion
（V2）及其最近一次审查——覆盖"这份合同现在是什么状态""风险点是什么""改了
什么""V2 审查结果如何"这几类最常见的问题。全部通过 ContractManager 现有的
只读方法获取，任何一步"还没有数据"（ContractNotFoundError）都当作"这部分
数据暂缺"处理，不让整个问答失败。
"""

from __future__ import annotations

from contract import ContractManager, ContractNotFoundError
from llm.client import LLMClientError, OpenAICompatibleClient
from prompts.qa import build_qa_messages


class QAServiceError(Exception):
    """QA 流程本身出错（LLM 调用失败等），不是"没有数据"这种正常情况。"""


class QAApplicationService:
    def __init__(self, contract_manager: ContractManager, llm_client: OpenAICompatibleClient) -> None:
        self.contract_manager = contract_manager
        self.llm_client = llm_client

    def answer(self, contract_id: str, question: str) -> str:
        """收集数据 → 拼 Prompt → 一次 LLM 调用 → 返回纯文本回答。

        contract_id 不存在时让 ContractManager.get_contract 的
        ContractNotFoundError 原样向上抛出（由调用方/API 层映射成 404），
        和这个项目里其它接口的一贯处理方式一致。
        """
        context = self._gather_context(contract_id)
        messages = build_qa_messages(context, question)
        try:
            return self.llm_client.chat(messages)
        except LLMClientError as exc:
            raise QAServiceError(f"问答调用 LLM 失败：{exc}") from exc

    def _gather_context(self, contract_id: str) -> str:
        contract = self.contract_manager.get_contract(contract_id)  # 不存在时直接抛出，不兜底
        lines: list[str] = [
            f"合同文件名：{contract.filename}",
            f"合同状态：{contract.status.value}",
        ]

        try:
            clauses = self.contract_manager.get_clauses(contract_id)
        except ContractNotFoundError:
            clauses = []
        top_level = [c for c in clauses if c.hierarchy_level == 0]
        if top_level:
            lines.append(f"条款数：{len(top_level)}")
            for c in top_level:
                snippet = c.original_text[:150].replace("\n", " ")
                lines.append(f"- {c.clause_id}（{c.clause_type}）：{snippet}")

        try:
            review = self.contract_manager.get_latest_review(contract_id)
        except ContractNotFoundError:
            review = None
        if review is not None:
            lines.append(
                f"最近一次审查（review_id={review.review_id}，contract_version={review.contract_version}）："
                f"总体风险等级={review.report.overall_risk_level.value}"
            )
            for r in review.report.results:
                ref = r.clause_id or r.rule_id or "(无关联条款)"
                lines.append(f"  - [{r.source.value}] {ref}：风险={r.risk_level.value}，理由={r.reason}")
            if review.report.failed_clauses:
                lines.append(f"审查失败的条款：{[f.clause_id for f in review.report.failed_clauses]}")

        try:
            tasks = self.contract_manager.list_modification_tasks(contract_id)
        except ContractNotFoundError:
            tasks = []
        for t in tasks:
            lines.append(
                f"修改任务 {t.task_id}（批次={t.batch_id}，条款={t.target_clause_id}，状态={t.status.value}）："
                f"律师意见={t.lawyer_instructions}"
            )
            for a in t.modification_attempts:
                risk_note = (
                    f"风险分析失败：{a.risk_analysis_error}"
                    if a.risk_analysis_error
                    else (f"修改后风险={a.risk_analysis.risk_level.value}" if a.risk_analysis else "未分析")
                )
                lines.append(
                    f"  - 第{a.attempt_number}轮：校验通过={a.validator_passed}，"
                    f"候选文本={(a.candidate_text or '')[:100]!r}，{risk_note}，"
                    f"风险化解结论={a.risk_resolution.value if a.risk_resolution else '无'}"
                )

        try:
            versions = self.contract_manager.list_versions(contract_id)
        except ContractNotFoundError:
            versions = []
        for v in versions:
            lines.append(f"版本 {v.version_number}（内部 contract_id={v.linked_contract_id}）")
            try:
                v2_review = self.contract_manager.get_latest_review(v.linked_contract_id)
            except ContractNotFoundError:
                v2_review = None
            if v2_review is not None:
                lines.append(
                    f"  V2 最近一次审查（review_id={v2_review.review_id}）："
                    f"总体风险等级={v2_review.report.overall_risk_level.value}"
                )

        return "\n".join(lines)
