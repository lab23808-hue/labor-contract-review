"""RAG 检索质量基线评估（第一阶段）：用真实 BGE-M3 + 真实 Chroma 检索，
对 data/eval_samples/retrieval_eval_samples.json 里 evaluable=True 的样本
批量检索，和标准答案的 legal_basis 比对，算 Recall@5 / MRR@5 / nDCG@5。

运行前提：
    1. 先跑一次 `python scripts/build_retrieval_eval_samples.py`，生成
       data/eval_samples/retrieval_eval_samples.json（本脚本只读这份文件，
       不会重新调用 generate_query/重新解析标准答案，保证本次所有实验用的
       是同一份 query + 标签快照）。
    2. 需要真实 langchain_chroma / langchain_huggingface / sentence-transformers，
       以及联网下载（或已缓存）BGE-M3 权重——本脚本不接受用 FakeEmbeddings
       或任何模拟检索结果代替，发现跑不起来就报错退出，不降级。

安全隔离（见脚本内 `_assert_isolated_from_official_db`）：
    - 用 tempfile.mkdtemp() 建一个全新持久化目录，collection_name 用
      "retrieval_eval_baseline"（不是正式的 settings.CHROMA_COLLECTION_NAME）。
    - 启动时就断言这个临时目录和 settings.CHROMA_DIR 不是同一个路径、
      collection 名字也不是正式名字——如果断言失败就直接报错退出，不写入，
      不做任何"看起来安全就继续"的猜测。
    - finally 块里清理临时目录；不会调用任何会影响 data/chroma 的方法。

本脚本只读取 data/knowledge/*.txt 构建临时知识库、只调用
`LegalKnowledgeRetriever.search_legal_knowledge()` 做检索，不修改
`rag/retriever.py`/`rag/database.py`/`agents/review_agent.py` 的任何逻辑，
不是"为了让分数好看"而调整检索算法。
"""

import argparse
import json
import math
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from rag import ChromaKnowledgeBase, KnowledgeLoader, LegalKnowledgeRetriever, build_embedder  # noqa: E402

SAMPLES_PATH = PROJECT_ROOT / "data" / "eval_samples" / "retrieval_eval_samples.json"
RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples" / "results"
EVAL_COLLECTION_NAME = "retrieval_eval_baseline"
TOP_K = 5  # 对应 settings.RETRIEVAL_TOP_K 的当前值；这里写成常量，不随 settings 改动静默变化


def _assert_isolated_from_official_db(persist_dir: Path, collection_name: str) -> None:
    """启动前的安全检查：临时库绝不能和正式库撞路径/撞 collection 名字。

    这是"如果无法确认数据库隔离是否安全，立即停止写入"这条要求的具体落实——
    不是口头承诺"会用临时目录"，而是真的在写入前做一次断言，撞了就直接
    AssertionError 中断，不继续往下跑。
    """
    official_dir = settings.CHROMA_DIR.resolve()
    temp_dir = persist_dir.resolve()
    assert temp_dir != official_dir, f"临时持久化目录和正式目录撞了：{temp_dir}，已中止，未写入任何数据"
    assert not str(temp_dir).startswith(str(official_dir)), f"临时目录在正式目录内部：{temp_dir}，已中止"
    assert collection_name != settings.CHROMA_COLLECTION_NAME, (
        f"临时 collection 名字和正式 collection 名字（{settings.CHROMA_COLLECTION_NAME}）相同，已中止"
    )


def _load_samples() -> dict:
    if not SAMPLES_PATH.exists():
        raise SystemExit(
            f"找不到 {SAMPLES_PATH}。请先运行 "
            "`python scripts/build_retrieval_eval_samples.py` 生成评估样本快照。"
        )
    return json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))


def _dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def _score_sample(sample: dict, evidences: list) -> dict:
    """拿检索到的 Evidence 列表，和样本的 relevant 标签比对，算这一条样本的
    Recall@5 / 首个相关结果的排名 / nDCG@5。

    匹配规则：Evidence.source 和 Evidence.article 分别对应标签里的
    "source"/"article"，必须两者都一致才算命中——不是只比条号字符串
    （见本次之前几轮分析指出的、"只比条号不比书名"会有误判风险这一点）。
    """
    relevant_pairs = {(r["source"], r["article"]) for r in sample["relevant"]}
    retrieved_pairs = [(e.source, e.article) for e in evidences[:TOP_K]]

    hit_ranks = [i + 1 for i, pair in enumerate(retrieved_pairs) if pair in relevant_pairs]
    distinct_hits = {pair for pair in retrieved_pairs if pair in relevant_pairs}

    recall_at_5 = len(distinct_hits) / len(relevant_pairs) if relevant_pairs else None
    first_hit_rank = hit_ranks[0] if hit_ranks else None
    mrr_contribution = 1.0 / first_hit_rank if first_hit_rank else 0.0

    relevances = [1 if pair in relevant_pairs else 0 for pair in retrieved_pairs]
    dcg = _dcg(relevances)
    ideal_hits = min(len(relevant_pairs), TOP_K)
    idcg = _dcg([1] * ideal_hits)
    ndcg = dcg / idcg if idcg > 0 else None

    return {
        "sample_id": sample["sample_id"],
        "recall_at_5": recall_at_5,
        "mrr_contribution": mrr_contribution,
        "first_hit_rank": first_hit_rank,
        "ndcg_at_5": ndcg,
        "relevant_pairs": sorted(relevant_pairs),
        "retrieved_top5": [
            {"source": e.source, "article": e.article, "score": e.metadata.get("score"),
             "content_preview": (e.content[:60] + "…") if len(e.content) > 60 else e.content}
            for e in evidences[:TOP_K]
        ],
    }


def run(limit: int | None = None) -> dict:
    payload = _load_samples()
    all_samples = payload["samples"]
    evaluable = [s for s in all_samples if s["evaluable"]]
    if limit:
        evaluable = evaluable[:limit]

    if not evaluable:
        raise SystemExit("没有 evaluable=True 的样本，无法评估——请检查 retrieval_eval_samples.json")

    persist_dir = Path(tempfile.mkdtemp(prefix="eval_retrieval_baseline_"))
    _assert_isolated_from_official_db(persist_dir, EVAL_COLLECTION_NAME)

    timing: dict = {}
    per_query_seconds: list[float] = []

    try:
        t0 = time.perf_counter()
        embedder = build_embedder()
        timing["embedder_load_seconds"] = round(time.perf_counter() - t0, 3)

        t1 = time.perf_counter()
        kb = ChromaKnowledgeBase(embedder, persist_directory=persist_dir, collection_name=EVAL_COLLECTION_NAME)
        loader = KnowledgeLoader(kb)
        files = sorted(settings.KNOWLEDGE_DIR.glob("*.txt"))
        for f in files:
            loader.load_and_index_file(f)
        timing["knowledge_base_build_seconds"] = round(time.perf_counter() - t1, 3)
        timing["knowledge_base_doc_count"] = kb.count()

        retriever = LegalKnowledgeRetriever(kb, top_k=TOP_K)

        per_sample_results = []
        for sample in evaluable:
            t2 = time.perf_counter()
            evidences = retriever.search_legal_knowledge(sample["query"], k=TOP_K)
            elapsed = time.perf_counter() - t2
            per_query_seconds.append(elapsed)

            scored = _score_sample(sample, evidences)
            scored["retrieval_seconds"] = round(elapsed, 4)
            scored["original_text"] = sample["original_text"]
            scored["query"] = sample["query"]
            per_sample_results.append(scored)

        timing["retrieval_total_seconds"] = round(sum(per_query_seconds), 3)
        timing["retrieval_mean_seconds"] = round(statistics.mean(per_query_seconds), 4)
        timing["retrieval_median_seconds"] = round(statistics.median(per_query_seconds), 4)
        if len(per_query_seconds) > 1:
            timing["retrieval_p95_seconds"] = round(
                statistics.quantiles(per_query_seconds, n=100)[94], 4
            )
        timing["note"] = (
            "embedder_load_seconds=加载 BGE-M3 模型；knowledge_base_build_seconds="
            "把 data/knowledge 全部文本切分+向量化写入临时 collection 的耗时；"
            "retrieval_* 只统计逐条调用 search_legal_knowledge() 的耗时，"
            "不包含模型加载和知识库构建——三者是分开计时的，不要混在一起比较。"
        )

        recalls = [r["recall_at_5"] for r in per_sample_results if r["recall_at_5"] is not None]
        mrrs = [r["mrr_contribution"] for r in per_sample_results]
        ndcgs = [r["ndcg_at_5"] for r in per_sample_results if r["ndcg_at_5"] is not None]

        aggregate = {
            "evaluated_sample_count": len(per_sample_results),
            "recall_at_5": round(statistics.mean(recalls), 4) if recalls else None,
            "mrr_at_5": round(statistics.mean(mrrs), 4) if mrrs else None,
            "ndcg_at_5": round(statistics.mean(ndcgs), 4) if ndcgs else None,
            "fully_missed_count": sum(1 for r in per_sample_results if r["recall_at_5"] == 0),
            "fully_hit_count": sum(1 for r in per_sample_results if r["recall_at_5"] == 1.0),
            "partial_hit_count": sum(
                1 for r in per_sample_results if r["recall_at_5"] is not None and 0 < r["recall_at_5"] < 1.0
            ),
        }

        result = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "data_snapshot_generated_at": payload["generated_at"],
            "model_name": settings.EMBEDDING_MODEL_NAME,
            "top_k": TOP_K,
            "knowledge_dir": str(settings.KNOWLEDGE_DIR),
            "eval_collection_name": EVAL_COLLECTION_NAME,
            "eval_persist_dir": str(persist_dir),
            "official_persist_dir_untouched": str(settings.CHROMA_DIR),
            "total_clauses_in_snapshot": payload["total_clauses"],
            "evaluable_in_snapshot": payload["evaluable_count"],
            "evaluated_this_run": len(evaluable),
            "timing": timing,
            "aggregate": aggregate,
            "per_sample": per_sample_results,
        }
        return result
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)


def _print_summary(result: dict) -> None:
    agg = result["aggregate"]
    print("=" * 70)
    print(f"评估样本数: {agg['evaluated_sample_count']}  模型: {result['model_name']}  top_k={result['top_k']}")
    print(f"Recall@5 = {agg['recall_at_5']}")
    print(f"MRR@5    = {agg['mrr_at_5']}")
    print(f"nDCG@5   = {agg['ndcg_at_5']}")
    print(f"完全命中: {agg['fully_hit_count']}  部分命中: {agg['partial_hit_count']}  完全未命中: {agg['fully_missed_count']}")
    print(f"\n耗时: {result['timing']}")

    per_sample = result["per_sample"]
    successes = [r for r in per_sample if r["recall_at_5"] == 1.0][:3]
    failures = [r for r in per_sample if r["recall_at_5"] == 0][:3]

    print("\n--- 代表性成功样本 ---")
    for r in successes:
        print(f"[{r['sample_id']}] query={r['query'][:40]!r} 标准依据={r['relevant_pairs']} "
              f"首个命中排名={r['first_hit_rank']}")

    print("\n--- 代表性失败样本（标准依据不在 Top-5 内）---")
    for r in failures:
        print(f"[{r['sample_id']}]")
        print(f"  原文: {r['original_text'][:60]!r}")
        print(f"  query: {r['query']!r}")
        print(f"  标准依据: {r['relevant_pairs']}")
        print(f"  Top-5 实际检索结果: {r['retrieved_top5']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条 evaluable 样本（调试用，省略=跑全部）")
    parser.add_argument("--output", type=Path, default=None, help="结果 JSON 输出路径（默认带时间戳自动生成）")
    args = parser.parse_args()

    result = run(limit=args.limit)
    _print_summary(result)

    output_path = args.output or (
        RESULTS_DIR / f"retrieval_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")


if __name__ == "__main__":
    main()
