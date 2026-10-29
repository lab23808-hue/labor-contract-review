"""正式知识库初始化脚本：把 data/knowledge 下的法律文本用真实 BGE-M3 写入 data/index/chroma。

跟 scripts/verify_rag_pipeline.py 的区别：这个脚本写的是正式知识库（data/index/chroma，
retrieval/backends/dense/store.py 里的默认持久化目录和 collection），且强制使用真实 BGE-M3——
始终使用真实 BGE-M3；模型加载失败只报告环境问题（见 scripts/_common.py），不会换成假实现。

用法：
    python scripts/build_knowledge_base.py            # 重建：先清空 collection 再写入（默认，幂等）
    python scripts/build_knowledge_base.py --append    # 不清空，直接在现有数据上追加
"""

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import CHROMA_DIR, KNOWLEDGE_DIR  # noqa: E402
from retrieval import DenseBackend, KnowledgeLoader  # noqa: E402
from _common import load_real_embedder_or_exit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--append", action="store_true", help="不清空现有 collection，直接追加")
    args = parser.parse_args()

    files = sorted(KNOWLEDGE_DIR.glob("*.txt"))
    if not files:
        raise SystemExit(f"{KNOWLEDGE_DIR} 下没有找到 .txt 法律文本，无法初始化知识库")

    print("[1/3] 加载真实 BGE-M3 embedding（首次运行会下载模型权重，请耐心等待）...")
    embedder = load_real_embedder_or_exit()
    print("      模型加载成功\n")

    if not args.append:
        # 整体删除持久化目录，连同 reset() 无法清理的孤立 HNSW segment 目录一起清掉。
        shutil.rmtree(CHROMA_DIR, ignore_errors=True)

    kb = DenseBackend(embedder)  # 使用 retrieval/backends/dense 的默认 persist_directory + collection_name
    loader = KnowledgeLoader(kb)

    print(f"[2/3] 写入 {len(files)} 个法律文本文件：")
    total_chunks = 0
    for f in files:
        evidences = loader.load_and_index_file(f)
        total_chunks += len(evidences)
        print(f'      - {f.name}：{len(evidences)} 个 chunk（source="{f.stem}"）')

    expected = loader.count_evidences(KNOWLEDGE_DIR)
    actual = kb.count()
    if actual != expected:
        raise RuntimeError(
            f"知识库索引一致性校验失败：Chroma count={actual}，"
            f"知识库切分 Evidence 数={expected}（目录 {KNOWLEDGE_DIR}）"
        )

    print("\n[3/3] 完成")
    print(f"  文档数量（法律文本文件数）：{len(files)}")
    print(f"  chunk 数量（本次写入的 Evidence 数）：{total_chunks}")
    print(f"  一致性校验：Chroma count={actual} == 知识库 Evidence 数={expected}")
    print(f"  collection 名称：{kb.store.collection_name}")
    print(f"  持久化目录：{kb.store.persist_directory}")
    print(f"  collection 当前总文档数：{kb.count()}")


if __name__ == "__main__":
    main()
