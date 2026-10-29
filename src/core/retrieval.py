"""检索能力的稳定契约。

业务层只依赖这个 Protocol，不依赖任何具体检索实现
（BM25、Dense、未来的 GraphRAG 等）。
"""

from typing import Optional, Protocol

from core.evidence import Evidence


class RetrievalService(Protocol):
    def search_legal_knowledge(self, query: str, k: Optional[int] = None) -> list[Evidence]: ...
