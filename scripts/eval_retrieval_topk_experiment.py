"""Dense 检索 Top-K 控制变量实验：固定 query/标签/知识库/模型/检索实现，
只改变 top_k（5 / 10 / 20），看 Recall/MRR/nDCG 怎么变、原先漏检的法条能不能
靠扩大候选数量找回来。

和 eval_retrieval_baseline.py 的关系：
    复用同一份 data/eval_samples/retrieval_eval_samples.json 样本快照、
    同一个 ChromaKnowledgeBase/KnowledgeLoader/LegalKnowledgeRetriever，
    不修改 rag/retriever.py、rag/database.py、generate_query()——
    唯一的自变量是传给 LegalKnowledgeRetriever.search_legal_knowledge() 的 k。

关键设计决定（对应用户要求，逐条说明）：
    1. **按不同的实际 query 组织检索，但 K=5/10/20 分别真实调用三次**，不是
       只跑一次 K=20 然后自己切片当成 K=5/K=10 的结果——chromadb 底层是
       HNSW 近似最近邻，不保证"K=20 的前 5 名"和"单独查 K=5"逐位完全一致，
       这里显式三次调用，并且在结果里记录两者是否一致（`prefix_consistency`
       字段），不去假定它们必然相同。
    2. 按 (query, 标签) 去重组织检索——同一个 query 在同一个临时知识库里
       检索结果必然相同（BGE-M3 推理和 Chroma 检索都是确定性的，没有随机
       采样），所以 188 条样本里只有 47 个不同的 (query, 标签) 场景，
       只对这 47 个场景分别跑 K=5/10/20，而不是对 188 条样本各跑一遍——
       省时间，但结果通过 sample_id 映射回全部 188 条样本，不丢失、不合并
       任何一条原始标准答案。
    3. 两套指标口径：
       - "原始样本口径"：188 条样本各自算一遍指标再宏平均（和旧基线的口径
         完全对齐，可以直接比较）。
       - "独立场景口径"：47 个场景各自算一遍指标再宏平均，每个场景权重相等，
         不管它在原始样本里重复了多少次。
       两套分开输出，不混在一个数字里。

安全隔离：沿用 eval_retrieval_baseline.py 的模式——临时持久化目录 +
独立 collection 名（这次用 "retrieval_topk_experiment"，和基线实验的
"retrieval_eval_baseline" 也不同，避免互相干扰），启动时断言不等于正式库，
不写入、不清空、不重建 data/chroma。
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
EVAL_COLLECTION_NAME = "retrieval_topk_experiment"
K_VALUES = [5, 10, 20]


def _assert_isolated_from_official_db(persist_dir: Path, collection_name: str) -> None:
    official_dir = settings.CHROMA_DIR.resolve()
    temp_dir = persist_dir.resolve()
    assert temp_dir != official_dir, f"临时持久化目录和正式目录撞了：{temp_dir}，已中止"
    assert not str(temp_dir).startswith(str(official_dir)), f"临时目录在正式目录内部：{temp_dir}，已中止"
    assert collection_name != settings.CHROMA_COLLECTION_NAME, "临时 collection 名字和正式名字相同，已中止"


def _load_evaluable_samples() -> list[dict]:
    if not SAMPLES_PATH.exists():
        raise SystemExit(f"找不到 {SAMPLES_PATH}，请先运行 build_retrieval_eval_samples.py")
    payload = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    return [s for s in payload["samples"] if s["evaluable"]]


def _label_key(sample: dict) -> tuple:
    return tuple(sorted((r["source"], r["article"]) for r in sample["relevant"]))


def _dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def _score(relevant_pairs: set, retrieved_pairs: list, k: int) -> dict:
    window = retrieved_pairs[:k]
    hit_positions = [i + 1 for i, pair in enumerate(window) if pair in relevant_pairs]
    distinct_hits = {pair for pair in window if pair in relevant_pairs}
    recall = len(distinct_hits) / len(relevant_pairs) if relevant_pairs else None
    first_rank = hit_positions[0] if hit_positions else None
    mrr_contrib = 1.0 / first_rank if first_rank else 0.0
    rels = [1 if pair in relevant_pairs else 0 for pair in window]
    dcg = _dcg(rels)
    idcg = _dcg([1] * min(len(relevant_pairs), k))
    ndcg = dcg / idcg if idcg > 0 else None
    return {"recall": recall, "mrr_contribution": mrr_contrib, "first_hit_rank": first_rank, "ndcg": ndcg}


def run() -> dict:
    evaluable = _load_evaluable_samples()
    scenarios: dict[tuple, list[dict]] = {}
    for s in evaluable:
        key = (s["query"], _label_key(s))
        scenarios.setdefault(key, []).append(s)

    persist_dir = Path(tempfile.mkdtemp(prefix="eval_topk_experiment_"))
    _assert_isolated_from_official_db(persist_dir, EVAL_COLLECTION_NAME)

    timing: dict = {}
    per_query_seconds: dict[int, list[float]] = {k: [] for k in K_VALUES}

    try:
        t0 = time.perf_counter()
        embedder = build_embedder()
        timing["embedder_load_seconds"] = round(time.perf_counter() - t0, 3)

        t1 = time.perf_counter()
        kb = ChromaKnowledgeBase(embedder, persist_directory=persist_dir, collection_name=EVAL_COLLECTION_NAME)
        loader = KnowledgeLoader(kb)
        for f in sorted(settings.KNOWLEDGE_DIR.glob("*.txt")):
            loader.load_and_index_file(f)
        timing["knowledge_base_build_seconds"] = round(time.perf_counter() - t1, 3)
        timing["knowledge_base_doc_count"] = kb.count()

        retriever = LegalKnowledgeRetriever(kb)

        # 对每个不同 query：K=5/10/20 各真实调用一次，不互相复用结果。
        scenario_results = []
        for (query, label_key), members in scenarios.items():
            k_results = {}
            for k in K_VALUES:
                t2 = time.perf_counter()
                evidences = retriever.search_legal_knowledge(query, k=k)
                per_query_seconds[k].append(time.perf_counter() - t2)
                k_results[k] = [
                    {"source": e.source, "article": e.article, "score": e.metadata.get("score")}
                    for e in evidences
                ]

            # 一致性核查：K=20 结果的前 5/前 10，是否和单独查 K=5/K=10 完全一致。
            pairs20 = [(d["source"], d["article"]) for d in k_results[20]]
            pairs10 = [(d["source"], d["article"]) for d in k_results[10]]
            pairs5 = [(d["source"], d["article"]) for d in k_results[5]]
            prefix_consistency = {
                "k20_prefix5_equals_k5": pairs20[:5] == pairs5,
                "k20_prefix10_equals_k10": pairs20[:10] == pairs10,
                "k10_prefix5_equals_k5": pairs10[:5] == pairs5,
            }

            relevant_pairs = set(label_key)
            scores_by_k = {
                k: _score(relevant_pairs, [(d["source"], d["article"]) for d in k_results[k]], k)
                for k in K_VALUES
            }

            scenario_results.append(
                {
                    "query": query,
                    "relevant_pairs": sorted(relevant_pairs),
                    "member_sample_ids": [m["sample_id"] for m in members],
                    "occurrence_count": len(members),
                    "retrieved": {str(k): k_results[k] for k in K_VALUES},
                    "prefix_consistency": prefix_consistency,
                    "scores_by_k": {str(k): scores_by_k[k] for k in K_VALUES},
                }
            )

        for k in K_VALUES:
            vals = per_query_seconds[k]
            timing[f"retrieval_k{k}_distinct_query_count"] = len(vals)
            timing[f"retrieval_k{k}_total_seconds"] = round(sum(vals), 3)
            timing[f"retrieval_k{k}_mean_seconds"] = round(statistics.mean(vals), 4)
        timing["note"] = (
            "retrieval_k{5,10,20}_* 是对 47 个【不同 query】分别计时，不是对 188 条样本计时——"
            "和旧基线 retrieval_baseline_*.json 里按 188 次调用算的耗时不是同一个口径，不能直接比较总耗时，"
            "但单次检索的均值/中位数量级可以比较。embedder_load/knowledge_base_build 和旧基线同口径。"
        )

        prefix_mismatches = [
            {"query": r["query"], "prefix_consistency": r["prefix_consistency"]}
            for r in scenario_results
            if not all(r["prefix_consistency"].values())
        ]

        # 口径 A：原始样本口径（188 条，按 sample_id 展开场景结果）
        sample_level = {str(k): [] for k in K_VALUES}
        for r in scenario_results:
            for k in K_VALUES:
                for sid in r["member_sample_ids"]:
                    sample_level[str(k)].append({"sample_id": sid, **r["scores_by_k"][str(k)]})

        aggregate_sample_level = {}
        for k in K_VALUES:
            rows = sample_level[str(k)]
            recalls = [x["recall"] for x in rows if x["recall"] is not None]
            mrrs = [x["mrr_contribution"] for x in rows]
            ndcgs = [x["ndcg"] for x in rows if x["ndcg"] is not None]
            aggregate_sample_level[str(k)] = {
                "n": len(rows),
                "recall": round(statistics.mean(recalls), 4) if recalls else None,
                "mrr": round(statistics.mean(mrrs), 4) if mrrs else None,
                "ndcg": round(statistics.mean(ndcgs), 4) if ndcgs else None,
            }

        # 口径 B：独立场景口径（47 个场景，权重相等）
        aggregate_scenario_level = {}
        for k in K_VALUES:
            recalls = [r["scores_by_k"][str(k)]["recall"] for r in scenario_results if r["scores_by_k"][str(k)]["recall"] is not None]
            mrrs = [r["scores_by_k"][str(k)]["mrr_contribution"] for r in scenario_results]
            ndcgs = [r["scores_by_k"][str(k)]["ndcg"] for r in scenario_results if r["scores_by_k"][str(k)]["ndcg"] is not None]
            aggregate_scenario_level[str(k)] = {
                "n": len(scenario_results),
                "recall": round(statistics.mean(recalls), 4) if recalls else None,
                "mrr": round(statistics.mean(mrrs), 4) if mrrs else None,
                "ndcg": round(statistics.mean(ndcgs), 4) if ndcgs else None,
            }

        result = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "model_name": settings.EMBEDDING_MODEL_NAME,
            "k_values": K_VALUES,
            "eval_collection_name": EVAL_COLLECTION_NAME,
            "eval_persist_dir": str(persist_dir),
            "official_persist_dir_untouched": str(settings.CHROMA_DIR),
            "total_evaluable_samples": len(evaluable),
            "distinct_scenario_count": len(scenario_results),
            "timing": timing,
            "prefix_mismatch_count": len(prefix_mismatches),
            "prefix_mismatches": prefix_mismatches,
            "aggregate_sample_level": aggregate_sample_level,
            "aggregate_scenario_level": aggregate_scenario_level,
            "scenarios": scenario_results,
        }
        return result
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)


def _print_summary(result: dict) -> None:
    print("=" * 70)
    print(f"样本总数: {result['total_evaluable_samples']}  独立场景数: {result['distinct_scenario_count']}")
    print(f"K=20 前缀与单独 K=5/K=10 不一致的场景数: {result['prefix_mismatch_count']}")
    print("\n--- 原始样本口径（188条，宏平均）---")
    for k, agg in result["aggregate_sample_level"].items():
        print(f"K={k}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}  (n={agg['n']})")
    print("\n--- 独立场景口径（47个场景，等权重）---")
    for k, agg in result["aggregate_scenario_level"].items():
        print(f"K={k}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}  (n={agg['n']})")
    print(f"\n耗时: {result['timing']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = run()
    _print_summary(result)

    output_path = args.output or (
        RESULTS_DIR / f"retrieval_topk_experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")


if __name__ == "__main__":
    main()
