"""HybridBackend：Dense + BM25 双路召回，再用 RRF 融合。"""

from __future__ import annotations

import hashlib

from langchain_core.documents import Document

from retrieval.fusion import rrf_scores


def _doc_key(document: Document) -> str:
    metadata = document.metadata or {}
    raw = "\x00".join(
        str(metadata.get(name, "")) for name in ("source", "article", "part")
    ) + "\x00" + document.page_content
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class HybridBackend:
    def __init__(self, dense, lexical, candidate_multiplier: int = 2) -> None:
        self.dense = dense
        self.lexical = lexical
        self.candidate_multiplier = candidate_multiplier

    def similarity_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        candidate_k = max(k, k * self.candidate_multiplier)
        dense_results = self.dense.similarity_search(query, k=candidate_k)
        lexical_results = self.lexical.similarity_search(query, k=candidate_k)

        documents: dict[str, Document] = {}
        rankings: list[list[str]] = []
        for results in (dense_results, lexical_results):
            ranking: list[str] = []
            for document, _score in results:
                key = _doc_key(document)
                documents.setdefault(key, document)
                if key not in ranking:
                    ranking.append(key)
            rankings.append(ranking)

        scores = rrf_scores(rankings, k=60)
        ordered = sorted(scores, key=lambda key: (-scores[key], key))[:k]
        return [(documents[key], scores[key]) for key in ordered]

    def count(self) -> int:
        return self.dense.count()
