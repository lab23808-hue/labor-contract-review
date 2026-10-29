"""RRF（Reciprocal Rank Fusion）纯函数。"""

from __future__ import annotations


def rrf_scores(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """rankings 每路已按相关性排序；返回 doc_id → RRF 分数。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    """按 RRF 分数降序返回 doc_id；同分按 id 排序保证稳定。"""
    scores = rrf_scores(rankings, k=k)
    return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
