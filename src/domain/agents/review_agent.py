"""ClauseReviewer：单条 Clause 的完整审查链路。

    Clause → 生成 query → LegalKnowledgeRetriever 检索 Evidence
           → prompts.review 构造 messages → llm client 调用 → 校验 JSON
           → 补全字段 → schemas.ReviewResult

依赖边界：
    - schemas（Clause、Evidence、ReviewResult、ReviewSource）
    - rag（只用 LegalKnowledgeRetriever，不碰 database.py / knowledge_loader.py）
    - llm.client（LLM 连接层） + prompts.review（Prompt 模板）
    - agents.review_schemas.LLMReviewOutput（本模块自己的“LLM 原始输出”结构）
    不依赖 contract/document 业务模块——Clause 对象从外部传入，
    本模块不关心它是怎么切出来的；也不依赖 workflows/*。

目前是单条顺序调用，没有引入 LangGraph 或任何编排框架；
多条款/多阶段的整体编排由 workflows.review_workflow 负责。
"""

import json
import re

from pydantic import ValidationError

from domain.agents.review_schemas import LLMReviewOutput
from config import settings
from infra.llm.client import LLMClientError, OpenAICompatibleClient
from domain.prompts.review import build_review_messages
from core.retrieval import RetrievalService
from core import Clause, ReviewResult, ReviewSource

_ARTICLE_NUMBER_RE = re.compile(r"^第[一二三四五六七八九十百千零〇两\d]+条[ \t　]*")
_ITEM_PREFIX_RE = re.compile(r"^(?:\d+[.．、]|[（(][一二三四五六七八九十\d]+[）)])\s*")


class ReviewError(Exception):
    """单条款审查过程中出现的错误（检索失败、LLM 调用失败、LLM 输出不合法）。

    不做静默兜底：出问题就抛出来，由调用方（workflows.review_workflow）决定
    怎么处理单条失败，例如记进 ReviewReport.failed_clauses。
    """


def generate_query(clause: Clause) -> str:
    """从条款原文生成检索 query。

    只去掉“第X条”这个编号本身（以及紧跟着的空白），保留标题文字和正文——
    只把“1.”“（一）”这类编号前缀当成纯噪音去掉。

    之前的版本会把“第X条 标题”整行都去掉，结果暴露了一个问题：条款标题
    （比如“竞业限制”）往往是最精准的法律术语，正文反而经常是同义改写、
    不出现这个词的口语化表达（比如“不得到有竞争关系的单位任职”）——把标题
    整行删掉会让检索丢失最有效的关键词。真实链路验证（见对话记录）就复现了
    这个问题：去标题后的 query 检索不到竞业限制相关的法条。
    """
    text = _ARTICLE_NUMBER_RE.sub("", clause.original_text, count=1)
    text = _ITEM_PREFIX_RE.sub("", text, count=1)
    text = text.strip()
    return text or clause.original_text.strip()


class ClauseReviewer:
    """单条 Clause 的审查器：把检索、Prompt、LLM 调用串成一条链路。"""

    def __init__(
        self,
        retriever: RetrievalService,
        llm_client: OpenAICompatibleClient,
        top_k: int = settings.RETRIEVAL_TOP_K,
    ) -> None:
        self.retriever = retriever
        self.llm_client = llm_client
        self.top_k = top_k

    def review(self, clause: Clause) -> ReviewResult:
        """跑完整条链路，返回 schemas.ReviewResult（source=llm）。"""
        query = generate_query(clause)

        try:
            evidence = self.retriever.search_legal_knowledge(query, k=self.top_k)
        except Exception as exc:
            raise ReviewError(
                f"检索法律依据失败（clause_id={clause.clause_id}，query={query!r}）：{exc}"
            ) from exc

        messages = build_review_messages(
            clause_text=clause.original_text,
            clause_type=clause.clause_type,
            evidence=evidence,
        )

        try:
            raw_output = self.llm_client.chat(messages, json_mode=True)
        except LLMClientError as exc:
            raise ReviewError(f"调用 LLM 失败（clause_id={clause.clause_id}）：{exc}") from exc

        llm_result = self._parse_llm_output(raw_output, clause_id=clause.clause_id)

        return ReviewResult(
            clause_id=clause.clause_id,
            risk=llm_result.risk,
            risk_level=llm_result.risk_level,
            reason=llm_result.reason,
            legal_basis=llm_result.legal_basis,
            suggestion=llm_result.suggestion,
            source=ReviewSource.LLM,
        )

    @staticmethod
    def _parse_llm_output(raw_output: str, clause_id: str) -> LLMReviewOutput:
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ReviewError(
                f"LLM 输出不是合法 JSON（clause_id={clause_id}）：{exc}\n原始输出：{raw_output!r}"
            ) from exc
        try:
            return LLMReviewOutput(**data)
        except (TypeError, ValidationError) as exc:
            raise ReviewError(
                f"LLM 输出的 JSON 不符合预期结构（clause_id={clause_id}）：{exc}\n原始输出：{raw_output!r}"
            ) from exc
