"""评估指标纯函数：法条提取、Recall@K、MRR@K。"""

from __future__ import annotations

import re
from typing import Optional

_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零〇两\d]+条")


def extract_article(citation: str) -> Optional[str]:
    match = _ARTICLE_RE.search(citation)
    return match.group(0) if match else None


def recall_at_k(gold_articles: list[str], retrieved_articles: list[str], k: int = 5) -> Optional[float]:
    """gold 中任意一条出现在 top-k 即为命中；gold 为空时返回 None。"""
    gold = [a for a in (extract_article(x) for x in gold_articles) if a]
    if not gold:
        return None
    top = [extract_article(x) for x in retrieved_articles[:k]]
    return 1.0 if any(a in top for a in gold) else 0.0


def reciprocal_rank(gold_articles: list[str], retrieved_articles: list[str], k: int = 5) -> Optional[float]:
    """第一个命中的 gold 排名倒数；未命中返回 0；gold 为空返回 None。"""
    gold = {a for a in (extract_article(x) for x in gold_articles) if a}
    if not gold:
        return None
    for rank, citation in enumerate(retrieved_articles[:k], start=1):
        if extract_article(citation) in gold:
            return 1.0 / rank
    return 0.0


def mean(values: list[Optional[float]]) -> Optional[float]:
    usable = [v for v in values if v is not None]
    return round(sum(usable) / len(usable), 4) if usable else None
