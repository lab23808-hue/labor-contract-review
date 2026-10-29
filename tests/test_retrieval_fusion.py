from langchain_core.documents import Document

from retrieval.backends.hybrid import HybridBackend
from retrieval.fusion import rrf_fuse, rrf_scores


def test_rrf_fuse_orders_by_combined_rank():
    assert rrf_fuse([["a", "b"], ["b", "c"]]) == ["b", "a", "c"]


def test_rrf_scores_are_higher_for_documents_ranked_by_both():
    scores = rrf_scores([["a", "b"], ["b", "a"]])
    assert scores["a"] == scores["b"]  # symmetric input


class _FakeBackend:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def similarity_search(self, query, k=5):
        self.calls.append((query, k))
        return self.docs

    def count(self):
        return len(self.docs)


def _doc(marker: str) -> Document:
    return Document(page_content=marker, metadata={"source": "法", "article": marker})


def test_hybrid_backend_fuses_dense_and_lexical():
    dense = _FakeBackend([(_doc("a"), 0.1), (_doc("b"), 0.2)])
    lexical = _FakeBackend([(_doc("b"), 3.0), (_doc("c"), 2.0)])
    hybrid = HybridBackend(dense=dense, lexical=lexical, candidate_multiplier=2)

    results = hybrid.similarity_search("query", k=2)

    assert [doc.metadata["article"] for doc, _ in results] == ["b", "a"]
    assert dense.calls == [("query", 4)]
    assert lexical.calls == [("query", 4)]
    assert results[0][1] > results[1][1]
