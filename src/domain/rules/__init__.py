"""rules：主线路（RAG+LLM）之后的规则补充检查。

只依赖 schemas，不依赖 contract/parser/domain/document/retrieval/llm/review。
"""

from domain.rules.checker import RuleChecker
from domain.rules.merge import merge_review_results

__all__ = ["RuleChecker", "merge_review_results"]
