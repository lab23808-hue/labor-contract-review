"""RAG 真实链路验证脚本（独立测试流程，不修改任何已有模块）。

验证：
    Clause 文本 → 生成 query → LegalKnowledgeRetriever.search_legal_knowledge → Evidence

用法（需要联网，首次会下载 BGE-M3 模型权重，用真实语义检索）：
    python scripts/verify_rag_pipeline.py

query 由生产代码 agents.review_agent.generate_query 生成，和正式审查链路使用同一份实现。
知识库建在一个临时目录里，每次运行都是全新的、跑完自动删除，
不会污染 data/index/chroma 里正式的知识库，重复运行也不会累积重复数据。
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from domain.agents.review_agent import generate_query  # noqa: E402
from config import settings  # noqa: E402
from config.settings import KNOWLEDGE_DIR  # noqa: E402
from domain.document import ClauseSplitter  # noqa: E402
from retrieval import DenseBackend, KnowledgeLoader, LegalKnowledgeRetriever, build_embedder  # noqa: E402
from core import Evidence  # noqa: E402
from _samples import RAG_RETRIEVAL_SAMPLE  # noqa: E402


def build_knowledge_base(persist_dir: Path) -> DenseBackend:
    embedder = build_embedder()
    kb = DenseBackend(embedder, persist_directory=persist_dir, collection_name="verify_rag")

    loader = KnowledgeLoader(kb)
    files = sorted(KNOWLEDGE_DIR.glob("*.txt"))
    if not files:
        raise SystemExit(f"{KNOWLEDGE_DIR} 下没有找到 .txt 法律文本，无法验证")
    for f in files:
        loader.load_and_index_file(f)

    print(f"[知识库] 已从 {len(files)} 个文件加载 {kb.count()} 条法律依据到临时向量库\n")
    return kb


def print_result(evidence: Evidence, rank: int) -> None:
    score = evidence.metadata.get("score")
    score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
    heading = f"  #{rank} 《{evidence.source}》"
    if evidence.article:
        heading += f" {evidence.article}"
    heading += f"  (score={score_str}，越小越相似)"
    print(heading)
    preview = evidence.content if len(evidence.content) <= 60 else evidence.content[:60] + "…"
    print(f"      {preview}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=settings.RETRIEVAL_TOP_K, help=f"每个条款检索几条法律依据（默认 {settings.RETRIEVAL_TOP_K}）")
    args = parser.parse_args()

    persist_dir = Path(tempfile.mkdtemp(prefix="verify_rag_"))
    try:
        kb = build_knowledge_base(persist_dir)
        retriever = LegalKnowledgeRetriever(kb, top_k=args.top_k)

        clauses = [
            c
            for c in ClauseSplitter().split(RAG_RETRIEVAL_SAMPLE, contract_id="verify_demo")
            if c.original_text.strip()
        ]

        for clause in clauses:
            query = generate_query(clause)

            print("=" * 60)
            print(f"[Clause {clause.clause_id}] 原文：")
            for line in clause.original_text.splitlines():
                print(f"    {line}")
            print(f"[生成的 query] {query}")

            evidences = retriever.search_legal_knowledge(query)
            if not evidences:
                print("[检索结果] 未找到任何法律依据")
            else:
                print(f"[检索结果]（top {len(evidences)}）")
                for rank, evidence in enumerate(evidences, start=1):
                    print_result(evidence, rank)
            print()
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
