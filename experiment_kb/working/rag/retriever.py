"""LegalKnowledgeRetriever：对外提供“输入 query，返回 Evidence 列表”的检索接口。

本文件是业务层：接收合同条款生成的查询文本，调用 database.py 做向量检索，
把 Chroma 返回的 Document 转换成 Evidence。

只负责“找依据”，不做任何法律判断——法条是否真的适用、条款是否违规，
交给后续的 LLM 审查环节判断，不在本文件里处理。
"""

from typing import Optional

from config import settings
from rag.database import ChromaKnowledgeBase
from schemas import Evidence


class LegalKnowledgeRetriever:
    """法律知识检索器。"""

    def __init__(self, knowledge_base: ChromaKnowledgeBase, top_k: int = settings.RETRIEVAL_TOP_K) -> None:
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        self.knowledge_base = knowledge_base
        self.top_k = top_k

    def search_legal_knowledge(self, query: str, k: Optional[int] = None) -> list[Evidence]:
        """按语义相似度检索法律依据，按相关性从高到低排列。

        k 不传时使用构造时的 top_k。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空")
        results = self.knowledge_base.similarity_search(query, k=k if k is not None else self.top_k)
        return [self._to_evidence(doc, score) for doc, score in results]

    @staticmethod
    def _to_evidence(doc, score: float) -> Evidence:
        metadata = dict(doc.metadata)
        source = metadata.pop("source", "unknown")
        article = metadata.pop("article", None)
        metadata["score"] = score  # 相似度分数放进 metadata，不作为 Evidence 的一等字段
        return Evidence(content=doc.page_content, source=source, article=article, metadata=metadata)
