"""LLM Review 真实端到端验证脚本（独立测试流程，不修改任何已有模块）。

用真实 BGE-M3 + 真实 DeepSeek，直接调用 ClauseReviewer.review()，
验证的是“这条链路的实际效果好不好”，不是代码逻辑（代码逻辑已经用假依赖在
tests/test_review_reviewer.py 里覆盖过了）。

前提：
    1. 已经跑过 scripts/build_knowledge_base.py，data/index/chroma/ 里有正式知识库；
    2. .env 里配置了 DEEPSEEK_API_KEY（DEEPSEEK_MODEL 可选）。

用法：
    python scripts/verify_review_pipeline.py
    python scripts/verify_review_pipeline.py --top-k 5
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from domain.agents.review_agent import ClauseReviewer, ReviewError, generate_query  # noqa: E402
from config import settings  # noqa: E402
from domain.document import ClauseSplitter  # noqa: E402
from retrieval import LegalKnowledgeRetriever  # noqa: E402
from core import Clause  # noqa: E402
from _common import (  # noqa: E402
    build_real_llm_client_or_exit,
    load_real_embedder_or_exit,
    open_knowledge_base_or_exit,
)
from _samples import REVIEW_CASES_SAMPLE  # noqa: E402


# clause_id → 展示用的 clause_type（会被注入 Prompt，帮模型判断条款性质）
CLAUSE_TYPE_LABELS = {
    "clause_001": "试用期工资",
    "clause_002": "工作时间",
    "clause_003": "竞业限制",
}


def load_sample_clauses() -> list[Clause]:
    clauses = ClauseSplitter().split(REVIEW_CASES_SAMPLE, contract_id="verify_review_demo")
    labeled = []
    for clause in clauses:
        if not clause.original_text.strip():
            continue
        label = CLAUSE_TYPE_LABELS.get(clause.clause_id)
        if label:
            clause.clause_type = label  # Clause 不是 frozen 模型，直接赋值即可
        labeled.append(clause)
    return labeled


def print_divider(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=settings.RETRIEVAL_TOP_K, help=f"每个条款检索几条法律依据（默认 {settings.RETRIEVAL_TOP_K}）")
    args = parser.parse_args()

    print("[1/3] 加载真实 BGE-M3 embedding（首次运行会下载模型权重）...")
    embedder = load_real_embedder_or_exit()
    print("      完成\n")

    kb = open_knowledge_base_or_exit(embedder)  # 读取 data/index/chroma/ 里正式的知识库（只读）
    print(f'[知识库] collection="{kb.collection_name}"，共 {kb.count()} 条法律依据\n')

    print("[2/3] 构造真实 DeepSeek 客户端...")
    llm_client = build_real_llm_client_or_exit()
    print(f"      model={llm_client.model}\n")

    retriever = LegalKnowledgeRetriever(kb, top_k=args.top_k)
    reviewer = ClauseReviewer(retriever, llm_client, top_k=args.top_k)

    print("[3/3] 开始逐条审查\n")
    clauses = load_sample_clauses()

    for clause in clauses:
        print_divider(f"[Clause {clause.clause_id}] 类型：{clause.clause_type}")
        print("条款原文：")
        for line in clause.original_text.splitlines():
            print(f"    {line}")

        query = generate_query(clause)
        print(f"\n生成的 query：{query}")
        try:
            evidence = retriever.search_legal_knowledge(query, k=args.top_k)
        except Exception as exc:  # noqa: BLE001 - 仅用于展示，真正的检索仍由 reviewer 内部完成
            evidence = []
            print(f"（检索展示失败，不影响下面的审查结果：{exc}）")

        print("\n检索到的 Evidence：")
        if not evidence:
            print("    （无）")
        for i, ev in enumerate(evidence, start=1):
            score = ev.metadata.get("score")
            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
            preview = ev.content if len(ev.content) <= 50 else ev.content[:50] + "…"
            print(f"    [{i}] 《{ev.source}》{ev.article or ''} (distance={score_str})")
            print(f"        {preview}")

        print("\n最终 ReviewResult：")
        try:
            result = reviewer.review(clause)
        except ReviewError as exc:
            print(f"    审查失败：{exc}")
            continue

        print(f"    risk         = {result.risk}")
        print(f"    risk_level   = {result.risk_level.value}")
        print(f"    reason       = {result.reason}")
        print(f"    legal_basis  = {result.legal_basis}")
        print(f"    suggestion   = {result.suggestion}")


if __name__ == "__main__":
    main()
