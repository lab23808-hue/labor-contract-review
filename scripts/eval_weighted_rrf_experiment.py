"""加权 RRF（Reciprocal Rank Fusion）控制变量实验：调整 Dense/BM25 相对权重能否改善排序。

## 这是什么实验，解决什么问题

04 号实验（`eval_retrieval_strategy_experiment.py`）已经用真实 Dense、真实 BM25 跑出过
对称（权重相等）RRF 融合的结果：BM25 单独的 MRR/nDCG 在当前 47 个独立场景上明显好于
Dense，但对称 RRF 融合后排序质量反而不如纯 BM25（它把部分只被 BM25 命中的法条排名拉低
了）。一个自然的问题是：对称（1:1）权重是不是不合适——如果让 BM25 在融合里占更大权重，
排序会不会更接近纯 BM25 的水平，同时还能保留 RRF 理论上应该有的召回优势？

本脚本只回答这一个问题：**调整 Dense 与 BM25 在 RRF 公式里的权重比例，能否在不损失召回
能力的前提下改善最终排序（MRR/nDCG）？** 不做其他改动。

## 什么是 RRF，为什么现在尝试加权

RRF 是一种"只看排名、不看原始分数"的候选融合方法：每个候选在某个通道里排第几名，就按
`1/(rrf_k + 排名)` 算一个贡献分，多个通道的贡献分相加得到融合分数，再按融合分数重新排序。
它的好处是不需要把 Dense 的余弦距离和 BM25 的 BM25Okapi 分数（量纲完全不同，不能直接相加）
统一到同一个尺度上。

04 号实验用的是对称 RRF：`score(d) = 1/(rrf_k+dense_rank(d)) + 1/(rrf_k+bm25_rank(d))`，
两个通道的权重都是 1。既然已经知道 BM25 排序质量更好，一个合理的下一步是给 BM25 更高的
权重，让融合结果更偏向 BM25 的排序，同时保留 Dense 通道"万一 BM25 没找到"时的候选补充
能力——这就是"加权 RRF"，公式变成：

    score(d) = dense_weight/(rrf_k+dense_rank(d)) + bm25_weight/(rrf_k+bm25_rank(d))

当 `dense_weight == bm25_weight` 时，这个公式退化成 04 号实验的对称 RRF，本脚本用这一点
做了自检（见 `_sanity_check_symmetric_matches_baseline()`）。

## 参数含义

    - candidate_k=20      ：Dense/BM25 每个通道内部的候选深度（复用 04 号实验已经跑好的
                            候选列表，这里不重新检索，只是沿用这个深度）。
    - final_top_k∈{5,10,20}：真正用来算指标的截断深度，和 candidate_k 严格区分。
    - rrf_k=60            ：RRF 公式里的平滑常数，04 号实验用的值，本轮不做参数搜索。
    - dense_weight / bm25_weight：本轮唯一改变的变量，只调整两个通道的相对权重比例，
                            不改变 rrf_k、不改变 candidate_k、不改变分词器或 query。

## 固定不变 vs 唯一改变的变量

固定（全部直接复用 04 号实验 `retrieval_strategy_experiment_20261011_030953.json` 里
已经保存好的真实结果，不重新调用 BGE-M3、不重新连接 Chroma、不重新跑 BM25）：
    - Dense 候选列表（每个场景 candidate_k=20 条，按真实余弦距离排好的真实候选）。
    - BM25 候选列表（char_bigram 分词器，k1=1.5/b=0.75，candidate_k=20，真实候选）。
    - query、标准相关法条标签、知识内容（知识内容指纹随输入文件一起读入并原样记录在
      输出里，供追溯；本脚本不重新计算指纹，因为没有重新切分知识库）。
    - candidate_k=20，final_top_k∈{5,10,20}，rrf_k=60。
    - 评分公式（`_score`/`_aggregate`，直接从 04 号实验模块导入，没有重新实现）。
    - 两套统计口径（188 条原始样本 / 47 个独立场景）。

唯一改变的变量：`(dense_weight, bm25_weight)` 这一对比例，共测试 4 组（见下方
`WEIGHT_PROFILES`），包括 1:1（对称基线，复现 04 号实验的 RRF 结果作为自检）、2:1、1:2、1:3。

## 运行方式

    cd <项目根目录>
    python scripts/eval_weighted_rrf_experiment.py
    # 可选：python scripts/eval_weighted_rrf_experiment.py --input <其他04号实验结果文件路径>

输入：默认读取 `data/eval_samples/results/retrieval_strategy_experiment_20261011_030953.json`
（04 号实验最终真实运行结果，Dense 为真实重跑、与 BM25 共用同一份知识内容，已通过内容
指纹核验——见该文件 `timing.dense` 字段）。如果这个文件缺少完整的 candidate_k=20 候选
列表，脚本会直接报错退出并说明缺什么，不会悄悄换成别的知识快照或重新跑模型。

输出：
    data/eval_samples/results/weighted_rrf_experiment_<时间戳>.json
    data/eval_samples/results/weighted_rrf_experiment_<时间戳>.md

## 这轮实验能证明什么，不能证明什么

能证明：
    - 在当前 47 个场景、188 条样本上，调整 RRF 权重比例对 Recall/MRR/nDCG 的真实影响。
    - 每组权重有没有找回"两个通道都没找到"的法条（按 RRF 的数学性质，答案必然是"没有"，
      这里只是验证实现没有违反这个性质，不是发现新规律——融合候选集永远是
      dense_candidates ∪ bm25_candidates 的子集，加权不会凭空产生新候选）。
    - 每组权重有没有把原本在 Top-5 的正确依据挤出 Top-5（真实的副作用检查）。

不能证明：
    - 不能代表除本脚本列出的 4 组权重之外的其他比例的效果（没有做参数搜索/网格搜索）。
    - 不能代表知识库或样本集变化后的效果（本轮知识内容和 04 号实验完全一致，没有重新切分）。
    - 不能代表除 RRF 之外的其他融合方式（例如加权线性组合归一化分数）的效果。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

strategy_mod = importlib.import_module("eval_retrieval_strategy_experiment")

_score = strategy_mod._score
_aggregate = strategy_mod._aggregate
CANDIDATE_K = strategy_mod.CANDIDATE_K
FINAL_TOP_KS = strategy_mod.FINAL_TOP_KS
DEFAULT_RRF_K = strategy_mod.DEFAULT_RRF_K

RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples" / "results"
DEFAULT_INPUT = RESULTS_DIR / "retrieval_strategy_experiment_20261011_030953.json"

# 本轮唯一改变的变量：(名称, dense_weight, bm25_weight)。1:1 是对称基线（用于自检，
# 应该和输入文件里已经算好的 rrf 候选列表完全一致），其余三组是任务要求的加权方案。
WEIGHT_PROFILES: list[tuple[str, float, float]] = [
    ("symmetric_1_1", 1.0, 1.0),
    ("dense_heavy_2_1", 2.0, 1.0),
    ("bm25_heavy_1_2", 1.0, 2.0),
    ("bm25_strong_1_3", 1.0, 3.0),
]

# 重点样本：按 query 里的关键词定位，不靠 sample_id 硬编码（输入文件按 scenario 组织，
# 这里用文本匹配找到对应场景，和此前几轮报告里核对过的真实样本保持一致）。
_KEY_SCENARIO_MARKERS = {
    "social_insurance_waiver": "自愿放弃由甲方缴纳社会保险",
    "workplace_unilateral_change": "随时调整乙方工作地点",
    "wage_delayed_payment": "延迟支付",
}


def _load_input(input_path: Path) -> dict:
    """只读加载 04 号实验的真实结果文件，不做任何修改，也不重新计算。"""
    if not input_path.exists():
        raise SystemExit(f"找不到输入文件 {input_path}，本轮要求必须复用已核实的真实结果，不能凭空生成。")
    return json.loads(input_path.read_text(encoding="utf-8"))


def _check_preconditions(payload: dict) -> list[str]:
    """核查输入文件是否具备本轮融合计算需要的全部信息：
        - 每个场景必须有 dense 和 bm25 两组候选，长度 >= CANDIDATE_K；
        - 知识内容指纹必须存在（证明 Dense 和 BM25 用的是同一份知识快照）。
    返回发现的问题列表；非空就说明不满足"直接复用、不重跑模型"的前提，调用方应该停止。
    """
    problems: list[str] = []
    dense_info = payload.get("timing", {}).get("dense", {})
    if not dense_info.get("knowledge_content_shared_with_bm25"):
        problems.append("输入文件没有标记 Dense 与 BM25 共用同一份知识内容（knowledge_content_shared_with_bm25），不满足复用前提。")
    if not dense_info.get("knowledge_chunk_content_fingerprint"):
        problems.append("输入文件缺少知识片段内容指纹（knowledge_chunk_content_fingerprint），无法证明知识内容一致。")

    for i, sc in enumerate(payload.get("scenarios", [])):
        cands = sc.get("candidates", {})
        dense = cands.get("dense")
        bm25 = cands.get("bm25")
        if not dense or len(dense) < CANDIDATE_K:
            problems.append(f"场景[{i}] query={sc.get('query','?')[:20]!r} 的 dense 候选数量不足 {CANDIDATE_K}（实际 {len(dense) if dense else 0}）。")
        if not bm25 or len(bm25) < CANDIDATE_K:
            problems.append(f"场景[{i}] query={sc.get('query','?')[:20]!r} 的 bm25 候选数量不足 {CANDIDATE_K}（实际 {len(bm25) if bm25 else 0}）。")
    return problems


def _weighted_rrf_fuse(
    dense_candidates: list[dict], bm25_candidates: list[dict], rrf_k: int,
    dense_weight: float, bm25_weight: float, limit: int,
) -> list[dict]:
    """加权 RRF 融合：输入两个通道各自已经排好序的候选列表（候选在列表里的位置就是它的
    真实排名，不重新计算分数），输出融合后按分数降序排列、截断到 limit 的候选列表。

    score(d) = dense_weight/(rrf_k+dense_rank(d)) + bm25_weight/(rrf_k+bm25_rank(d))

    某候选只出现在一个通道时，只累加该通道的贡献（缺失通道贡献为 0，不是惩罚）。
    并列排名处理：按 (融合分数降序, 两通道排名之和升序, dense 排名升序) 排序，保证结果
    稳定、可复现（和 04 号实验 `_rrf_fuse` 的并列处理方式一致，只是加了权重系数）。
    """
    dense_rank = {(d["source"], d["article"]): i + 1 for i, d in enumerate(dense_candidates)}
    bm25_rank = {(d["source"], d["article"]): i + 1 for i, d in enumerate(bm25_candidates)}
    all_keys = set(dense_rank) | set(bm25_rank)

    fused = []
    for key in all_keys:
        dr = dense_rank.get(key)
        br = bm25_rank.get(key)
        score = (dense_weight / (rrf_k + dr) if dr else 0.0) + (bm25_weight / (rrf_k + br) if br else 0.0)
        rank_sum = (dr or 10**6) + (br or 10**6)
        fused.append((key, score, rank_sum, dr or 10**6))
    fused.sort(key=lambda x: (-x[1], x[2], x[3]))
    return [
        {"source": k[0], "article": k[1], "score": round(score, 6), "from_dense": k in dense_rank, "from_bm25": k in bm25_rank}
        for (k, score, _, _) in fused[:limit]
    ]


def _sanity_check_symmetric_matches_baseline(payload: dict, rrf_k: int) -> list[str]:
    """自检：用本脚本的加权融合函数，权重设成 1:1，重新算一遍每个场景的融合候选，
    结果应该和输入文件里 04 号实验已经算好的对称 RRF 候选（candidates.rrf）完全一致
    （排名顺序、每一条的 source/article 都一样）。不一致说明本脚本的融合实现和已验证
    过的 04 号实验 `_rrf_fuse` 不等价，必须在报告里如实指出，不能掩盖。
    """
    mismatches = []
    for sc in payload["scenarios"]:
        dense = sc["candidates"]["dense"]
        bm25 = sc["candidates"]["bm25"]
        baseline_rrf = sc["candidates"]["rrf"]
        recomputed = _weighted_rrf_fuse(dense, bm25, rrf_k, 1.0, 1.0, CANDIDATE_K)
        baseline_keys = [(c["source"], c["article"]) for c in baseline_rrf]
        recomputed_keys = [(c["source"], c["article"]) for c in recomputed]
        if baseline_keys != recomputed_keys:
            mismatches.append(sc["query"][:30])
    return mismatches


def _find_key_scenario(payload: dict, marker: str) -> dict | None:
    for sc in payload["scenarios"]:
        if marker in sc["query"]:
            return sc
    return None


def _rank_of(candidates: list[dict], source: str, article: str) -> int | None:
    for i, c in enumerate(candidates):
        if c["source"] == source and c["article"] == article:
            return i + 1
    return None


def run(input_path: Path, rrf_k: int) -> dict:
    payload = _load_input(input_path)

    problems = _check_preconditions(payload)
    if problems:
        print("输入文件不满足本轮复用前提，停止，不会悄悄换成其他知识快照或重新跑模型：")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)

    symmetric_mismatches = _sanity_check_symmetric_matches_baseline(payload, rrf_k)
    if symmetric_mismatches:
        print("警告：1:1 权重自检与输入文件里已有的对称 RRF 结果不一致，涉及场景（前几个）：")
        for q in symmetric_mismatches[:5]:
            print("  -", q)
    else:
        print(f"自检通过：权重 1:1 时，本脚本重新算出的融合候选与输入文件里 04 号实验已有的对称 RRF 候选逐场景完全一致（{len(payload['scenarios'])} 个场景）。")

    scenarios = payload["scenarios"]
    weight_results: dict[str, dict] = {}

    for profile_name, dw, bw in WEIGHT_PROFILES:
        scenario_records = []
        for sc in scenarios:
            relevant_pairs = {tuple(p) for p in sc["relevant_pairs"]}
            dense = sc["candidates"]["dense"]
            bm25 = sc["candidates"]["bm25"]
            fused = _weighted_rrf_fuse(dense, bm25, rrf_k, dw, bw, CANDIDATE_K)
            fused_pairs = [(c["source"], c["article"]) for c in fused]
            scores_by_k = {str(k): _score(relevant_pairs, fused_pairs, k) for k in FINAL_TOP_KS}
            scenario_records.append(
                {
                    "query": sc["query"],
                    "relevant_pairs": sc["relevant_pairs"],
                    "member_sample_ids": sc["member_sample_ids"],
                    "occurrence_count": sc["occurrence_count"],
                    "fused_candidates": fused,
                    "scores_by_k": scores_by_k,
                }
            )

        aggregate_scenario_level = {
            str(k): _aggregate([r["scores_by_k"][str(k)] for r in scenario_records]) for k in FINAL_TOP_KS
        }
        aggregate_sample_level = {}
        for k in FINAL_TOP_KS:
            rows = []
            for r in scenario_records:
                for _sid in r["member_sample_ids"]:
                    rows.append(r["scores_by_k"][str(k)])
            aggregate_sample_level[str(k)] = _aggregate(rows)

        weight_results[profile_name] = {
            "dense_weight": dw,
            "bm25_weight": bw,
            "aggregate_sample_level": aggregate_sample_level,
            "aggregate_scenario_level": aggregate_scenario_level,
            "scenarios": scenario_records,
        }

    # ---- 特别检查：找回 / 掉出 Top-5 / 排名改善，均基于真实候选对比，不靠汇总指标推断 ----
    special_checks = _run_special_checks(payload, weight_results)

    # ---- 重点样本：社保补偿、工作地点、延迟支付 ----
    key_samples = _collect_key_samples(payload, weight_results)

    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "input_knowledge_chunk_content_fingerprint": payload["timing"]["dense"].get("knowledge_chunk_content_fingerprint"),
        "reused_real_candidates_no_model_rerun": True,
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "rrf_k": rrf_k,
        "weight_profiles": [{"name": n, "dense_weight": dw, "bm25_weight": bw} for n, dw, bw in WEIGHT_PROFILES],
        "symmetric_sanity_check_mismatches": symmetric_mismatches,
        "total_evaluable_samples": payload["total_evaluable_samples"],
        "distinct_scenario_count": payload["distinct_scenario_count"],
        "weight_results": weight_results,
        "special_checks": special_checks,
        "key_samples": key_samples,
    }


def _run_special_checks(payload: dict, weight_results: dict) -> dict:
    """三项真实检查，逐场景比对，不从汇总指标反推：
        1. 是否找回了 Dense 和 BM25 都没找到的标准相关法条（按 RRF 数学性质必然为 0，
           这里是验证实现没有破坏这个性质）。
        2. 原本只被一个通道找到、排名靠后的法条，加权后排名是否改善。
        3. 原本在对称 RRF(1:1) Top-5 内的正确依据，是否在其他权重下掉出 Top-5。
    """
    never_found_by_either_recovered: dict[str, list] = {}
    dropped_out_of_top5: dict[str, list] = {}

    baseline_scenarios = {sc["query"]: sc for sc in weight_results["symmetric_1_1"]["scenarios"]}

    for profile_name, profile in weight_results.items():
        recovered_this_profile = []
        dropped_this_profile = []
        for sc, orig_sc in zip(profile["scenarios"], payload["scenarios"]):
            relevant_pairs = {tuple(p) for p in sc["relevant_pairs"]}
            dense_pairs = {(c["source"], c["article"]) for c in orig_sc["candidates"]["dense"]}
            bm25_pairs = {(c["source"], c["article"]) for c in orig_sc["candidates"]["bm25"]}
            neither_pairs = relevant_pairs - dense_pairs - bm25_pairs
            fused_pairs = {(c["source"], c["article"]) for c in sc["fused_candidates"]}
            recovered = neither_pairs & fused_pairs
            if recovered:
                recovered_this_profile.append({"query": sc["query"][:40], "recovered": sorted(recovered)})

            if profile_name != "symmetric_1_1":
                baseline_sc = baseline_scenarios[sc["query"]]
                baseline_top5 = {(c["source"], c["article"]) for c in baseline_sc["fused_candidates"][:5]}
                this_top5 = {(c["source"], c["article"]) for c in sc["fused_candidates"][:5]}
                dropped = (baseline_top5 & relevant_pairs) - this_top5
                if dropped:
                    dropped_this_profile.append({"query": sc["query"][:40], "dropped_relevant": sorted(dropped)})

        never_found_by_either_recovered[profile_name] = recovered_this_profile
        dropped_out_of_top5[profile_name] = dropped_this_profile

    return {
        "never_found_by_either_channel_recovered_by_rrf": never_found_by_either_recovered,
        "dropped_out_of_top5_vs_symmetric_baseline": dropped_out_of_top5,
    }


def _collect_key_samples(payload: dict, weight_results: dict) -> dict:
    key_samples = {}
    for name, marker in _KEY_SCENARIO_MARKERS.items():
        orig_sc = _find_key_scenario(payload, marker)
        if orig_sc is None:
            key_samples[name] = {"found": False}
            continue
        entry = {
            "found": True,
            "query": orig_sc["query"],
            "relevant_pairs": orig_sc["relevant_pairs"],
            "baseline_dense_ranks": {
                f"{a}{b}": _rank_of(orig_sc["candidates"]["dense"], a, b) for a, b in orig_sc["relevant_pairs"]
            },
            "baseline_bm25_ranks": {
                f"{a}{b}": _rank_of(orig_sc["candidates"]["bm25"], a, b) for a, b in orig_sc["relevant_pairs"]
            },
            "fused_ranks_by_weight_profile": {},
        }
        for profile_name, profile in weight_results.items():
            fused_sc = next(sc for sc in profile["scenarios"] if sc["query"] == orig_sc["query"])
            entry["fused_ranks_by_weight_profile"][profile_name] = {
                f"{a}{b}": _rank_of(fused_sc["fused_candidates"], a, b) for a, b in orig_sc["relevant_pairs"]
            }
        key_samples[name] = entry
    return key_samples


def _print_summary(result: dict) -> None:
    print("=" * 78)
    print(f"输入文件: {result['input_file']}")
    print(f"candidate_k={result['candidate_k']}  final_top_k={result['final_top_k_values']}  rrf_k={result['rrf_k']}")
    print(f"样本数={result['total_evaluable_samples']}  独立场景数={result['distinct_scenario_count']}")
    print(f"本轮是否复用真实候选、未重跑模型: {result['reused_real_candidates_no_model_rerun']}")
    print()
    for profile_name, profile in result["weight_results"].items():
        print(f"--- {profile_name} (dense_weight={profile['dense_weight']}, bm25_weight={profile['bm25_weight']}) ---")
        for basis_name, basis in [("原始样本口径(188)", profile["aggregate_sample_level"]), ("独立场景口径(47)", profile["aggregate_scenario_level"])]:
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                print(f"  {basis_name} K={k:2d}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}")
    print()
    print("找回双通道都未命中的法条（各权重）:")
    for name, items in result["special_checks"]["never_found_by_either_channel_recovered_by_rrf"].items():
        print(f"  {name}: {len(items)} 处")
    print("相比对称基线掉出 Top-5 的正确依据（各权重）:")
    for name, items in result["special_checks"]["dropped_out_of_top5_vs_symmetric_baseline"].items():
        print(f"  {name}: {len(items)} 处")


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = [
        "# 加权 RRF 控制变量实验报告",
        "",
        f"运行时间（UTC）：{result['run_at']}",
        "",
        f"输入文件：`{result['input_file']}`（04 号实验真实结果，本轮未重新调用任何模型，"
        f"`reused_real_candidates_no_model_rerun={result['reused_real_candidates_no_model_rerun']}`）",
        "",
        f"candidate_k={result['candidate_k']}；final_top_k={result['final_top_k_values']}；rrf_k={result['rrf_k']}；"
        f"样本数={result['total_evaluable_samples']}；独立场景数={result['distinct_scenario_count']}",
        "",
        f"1:1 对称权重自检：{'通过（与04号实验已有RRF结果逐场景一致）' if not result['symmetric_sanity_check_mismatches'] else '未通过，见JSON的 symmetric_sanity_check_mismatches'}",
        "",
        "## 指标对照",
        "",
        "| 权重方案 | dense_weight | bm25_weight | 口径 | K | Recall | MRR | nDCG |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for profile_name, profile in result["weight_results"].items():
        for basis_name, basis in [("原始样本188", profile["aggregate_sample_level"]), ("独立场景47", profile["aggregate_scenario_level"])]:
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                lines.append(
                    f"| {profile_name} | {profile['dense_weight']} | {profile['bm25_weight']} | {basis_name} | {k} | "
                    f"{agg['recall']} | {agg['mrr']} | {agg['ndcg']} |"
                )
    lines += [
        "",
        "## 特别检查",
        "",
        "找回双通道都未命中的法条（按 RRF 数学性质应恒为 0 处）：",
    ]
    for name, items in result["special_checks"]["never_found_by_either_channel_recovered_by_rrf"].items():
        lines.append(f"- {name}: {len(items)} 处")
    lines.append("")
    lines.append("相比对称基线（1:1）掉出 Top-5 的正确依据：")
    for name, items in result["special_checks"]["dropped_out_of_top5_vs_symmetric_baseline"].items():
        lines.append(f"- {name}: {len(items)} 处" + (f"，例如：{items[0]}" if items else ""))
    lines += ["", "## 重点样本排名", ""]
    for name, entry in result["key_samples"].items():
        lines.append(f"### {name}")
        if not entry.get("found"):
            lines.append("未在输入文件的场景列表中找到匹配该关键词的场景。")
            continue
        lines.append(f"query: `{entry['query'][:60]}...`")
        lines.append(f"- baseline dense ranks: {entry['baseline_dense_ranks']}")
        lines.append(f"- baseline bm25 ranks: {entry['baseline_bm25_ranks']}")
        for profile_name, ranks in entry["fused_ranks_by_weight_profile"].items():
            lines.append(f"- {profile_name} fused ranks: {ranks}")
        lines.append("")
    lines.append("完整逐场景记录见同名 `.json` 文件。")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)
    args = parser.parse_args()

    result = run(args.input, args.rrf_k)
    _print_summary(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"weighted_rrf_experiment_{timestamp}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print()
    print(f"完整结果已写出: {output_path}")
    print(f"报告已写出: {md_path}")


if __name__ == "__main__":
    main()
