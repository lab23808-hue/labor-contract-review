"""检索层的稳定 Protocol。

具体后端（Dense / BM25）只需要满足这些结构化接口，
LegalKnowledgeRetriever 不关心实现。
"""

from typing import Optional, Protocol

from langchain_core.documents import Document


class SimilaritySearchBackend(Protocol):
    def similarity_search(self, query: str, k: int) -> list[tuple[Document, float]]: ...


class VectorSink(Protocol):
    def add_texts(
        self, texts: list[str], metadatas: list[dict], ids: Optional[list[str]] = None
    ) -> list[str]: ...
