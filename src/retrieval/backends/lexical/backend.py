"""BM25 检索后端：BM25Index + 统一 similarity_search 接口。"""

from typing import Callable

from langchain_core.documents import Document

from core import Evidence

from .index import SCORE_TYPE, BM25Index, BM25IndexBuildError, char_bigram_tokenizer


class BM25Backend:
    """把 BM25Index 包装成 LegalKnowledgeRetriever 可用的检索后端。"""

    def __init__(
        self,
        evidences: list[Evidence],
        tokenize: Callable[[str], list[str]] = char_bigram_tokenizer,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.index = BM25Index(evidences, tokenize=tokenize, k1=k1, b=b)

    def similarity_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        results = self.index.similarity_search(query, k=k)
        return [(doc, score) for doc, score in results if score > 0]

    def count(self) -> int:
        return self.index.count()


__all__ = [
    "BM25Backend",
    "BM25Index",
    "BM25IndexBuildError",
    "char_bigram_tokenizer",
    "SCORE_TYPE",
]
