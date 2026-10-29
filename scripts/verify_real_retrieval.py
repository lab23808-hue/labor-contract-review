"""正式知识库真实检索验证：从已经持久化的 data/index/chroma 读取，用真实 BGE-M3 做检索。

跑之前请先运行 scripts/build_knowledge_base.py 完成初始化。本脚本只读，不写入数据。
始终使用真实 BGE-M3；模型加载失败只报告环境问题（见 scripts/_common.py），不会换成假实现。
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402
from retrieval import LegalKnowledgeRetriever  # noqa: E402
from _common import load_real_embedder_or_exit, open_knowledge_base_or_exit  # noqa: E402

TEST_QUERIES = [
    "试用期工资不得低于多少",
    "竞业限制期限",
    "劳动合同必备条款有哪些",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=settings.RETRIEVAL_TOP_K, help=f"每个 query 返回几条结果（默认 {settings.RETRIEVAL_TOP_K}）")
    args = parser.parse_args()

    print("加载真实 BGE-M3 embedding...")
    embedder = load_real_embedder_or_exit()
    print("模型加载成功\n")

    kb = open_knowledge_base_or_exit(embedder)  # 读取 data/index/chroma/ 里正式的知识库（只读）
    print(f'知识库当前共有 {kb.count()} 条文档（collection="{kb.collection_name}"）\n')

    retriever = LegalKnowledgeRetriever(kb, top_k=args.top_k)

    for query in TEST_QUERIES:
        print("=" * 60)
        print(f"[query] {query}")
        evidences = retriever.search_legal_knowledge(query)
        if not evidences:
            print("  未检索到任何结果")
            continue
        for rank, evidence in enumerate(evidences, start=1):
            score = evidence.metadata.get("score")
            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
            print(f"  #{rank} article={evidence.article!r}  source={evidence.source!r}  distance={score_str}")
            preview = evidence.content if len(evidence.content) <= 60 else evidence.content[:60] + "…"
            print(f"      {preview}")
        print()


if __name__ == "__main__":
    main()
