# -*- coding: utf-8 -*-
"""
experiment_kb/scripts/evaluate_contract_eval_500_full_kb.py

本轮“500份合同评测集全量知识库检索实验”的可复现评测脚本。

- 调用生产实现 rag.bm25_index.BM25KnowledgeIndex（char_bigram tokenizer, k1=1.5, b=0.75），
  不重新实现、不改写BM25算法本身。
- 知识库来源：
    1) data/knowledge/ 生产知识内容（劳动合同法.txt，26条Evidence）
    2) experiment_kb/working/ 的全部37条核心Evidence中，新增的11条（LAW_01第五十条 +
       LAW_02第三十六—四十五条），用于与生产数据合并
    3) experiment_kb/reference_only/ 的仲裁法第十—十六条参考材料（仅进入本轮实验隔离索引，
       不进入正式生产知识库）
    4) experiment_kb/baseline/ 作为历史快照起点，仅用于比对，不作为独立法律内容重复合并
  四者合并后经生产 KnowledgeLoader 真实解析、去重，得到本轮实验完整知识库。
- 对450份新合同 + 现有50份(188条可评估样本) 执行真实检索，分口径(A/B/C)输出指标。
- 所有产出文件只写入 experiment_kb/ 下，不写入生产业务数据目录。

本脚本设计为既可在设备原机（真实生产环境，已安装真实langchain系依赖）上直接运行，
也可在云端沙箱（真实生产代码 + 轻量占位langchain模块，通过conftest_fakes.py注入）中运行；
两种环境的切换是全自动的（见下方"可选沙箱占位注入"），不需要手改代码。
路径通过顶部常量配置，便于复现。
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
import time
import platform
from pathlib import Path
from collections import defaultdict, Counter

# ---------------------------------------------------------------------------
# 路径配置（复现时按实际机器调整这几个常量即可，其余逻辑不变）
# 默认值已设为设备原机的真实项目路径；在云端沙箱里运行时可通过命令行/环境变量覆盖，
# 或直接改这里的默认值——具体见下方 if __name__ == "__main__" 之前的覆盖逻辑。
# ---------------------------------------------------------------------------
import os
PROJECT_ROOT = Path(os.environ.get("LCR_PROJECT_ROOT", r"C:\Javase\pythonproject\labor_contract_review"))
# SANDBOX_SRC_ROOT 只在"真实项目依赖(langchain_core等)不可用"的环境下才会被用到
# （典型场景：云端沙箱）。设备原机上已安装真实依赖，不会用到这个目录，也不要求它存在。
SANDBOX_SRC_ROOT = Path("/home/claude/work/labor_contract_review")
DATASET_ROOT = PROJECT_ROOT / "experiment_kb" / "datasets" / "contract_eval_500_20261013"
OUT_DIR = DATASET_ROOT / "full_kb_experiment"
OLD_EVAL_SAMPLES = PROJECT_ROOT / "experiment_kb" / "working" / "data" / "eval_samples" / "retrieval_eval_samples.json"

# ---------------------------------------------------------------------------
# 可选沙箱占位注入：
# 设备原机上本来就装有真实的 langchain_core / langchain_text_splitters 等依赖
# （生产代码本来就靠它们运行），所以这里优先尝试把 PROJECT_ROOT 直接加入 sys.path
# 并正常 import 真实的 rag.* 包——不注入任何占位模块。
# 只有当这些真实依赖在当前环境中确实缺失时（比如本脚本在没装这些包的云端沙箱里跑），
# 才会退回去尝试加载 SANDBOX_SRC_ROOT 下的 conftest_fakes.py 占位方案；
# 如果两条路都找不到可用依赖，会给出清晰的报错而不是含糊的 ModuleNotFoundError。
# ---------------------------------------------------------------------------
sys.path.insert(0, str(PROJECT_ROOT))
try:
    from rag.knowledge_loader import KnowledgeLoader  # noqa: E402
    from rag.bm25_index import BM25KnowledgeIndex  # noqa: E402
    from rag.retriever import LegalKnowledgeRetriever  # noqa: E402
    import rag.database as fake_db  # noqa: E402  (设备原机上这是真实的rag.database模块)
except ModuleNotFoundError as e:
    if str(SANDBOX_SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SANDBOX_SRC_ROOT))
    try:
        import conftest_fakes  # noqa: E402,F401  （仅沙箱占位环境需要，设备原机不需要也不应存在）
        from rag.knowledge_loader import KnowledgeLoader  # noqa: E402
        from rag.bm25_index import BM25KnowledgeIndex  # noqa: E402
        from rag.retriever import LegalKnowledgeRetriever  # noqa: E402
        import rag.database as fake_db  # noqa: E402
    except ModuleNotFoundError:
        raise RuntimeError(
            "无法导入 rag.* 生产模块：既不是真实依赖(langchain_core等)缺失的设备原机环境，"
            "也没有找到沙箱占位方案(conftest_fakes.py)。请确认 PROJECT_ROOT 路径正确，"
            "且该环境已安装 requirements 中的真实依赖。原始错误: " + repr(e)
        )

CANDIDATE_K = 20
FINAL_TOP_KS = [5, 10, 20]
RUN_UTC_NOTE = "见 run_metadata.json 的 generated_at 字段"

# ---------------------------------------------------------------------------
# 1. 构建本轮“完整实验知识库” —— 复用生产 KnowledgeLoader.load_file，显式指定
#    source 为规范法律名称（这是 load_file 本身支持的既有参数，不是修改生产逻辑）。
# ---------------------------------------------------------------------------
KB_SOURCE_FILES = [
    ("production", PROJECT_ROOT / "data" / "knowledge" / "劳动合同法.txt", "劳动合同法"),
    ("working_new", PROJECT_ROOT / "experiment_kb" / "working" / "data" / "knowledge" / "LAW_01_劳动合同法_第五十条.txt", "劳动合同法"),
    ("working_new", PROJECT_ROOT / "experiment_kb" / "working" / "data" / "knowledge" / "LAW_02_劳动法_第三十六条至第四十五条.txt", "劳动法"),
    ("reference_only", PROJECT_ROOT / "experiment_kb" / "reference_only" / "仲裁法_第十条至第十六条_参考材料.txt", "劳动争议调解仲裁法"),
]


def build_full_kb():
    loader = KnowledgeLoader(knowledge_base=fake_db.ChromaKnowledgeBase.__new__(fake_db.ChromaKnowledgeBase))
    all_evidences = []
    manifest_rows = []
    for origin, path, law_name in KB_SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        evs = loader.load_file(str(path), source=law_name)
        for ev in evs:
            eid = KnowledgeLoader._evidence_id(ev)
            all_evidences.append((origin, str(path), ev, eid))
            manifest_rows.append({
                "origin": origin,
                "origin_file": str(path),
                "origin_file_sha256": file_hash,
                "source": ev.source,
                "article": ev.article,
                "part": ev.metadata.get("part", ""),
                "content_length": len(ev.content),
                "content_sha256": hashlib.sha256(ev.content.encode("utf-8")).hexdigest(),
                "evidence_id": eid,
            })

    # 真实去重校验（与生产 BM25KnowledgeIndex 的 fail-fast 逻辑一致的 evidence_id 口径）
    seen = {}
    dupes = []
    for origin, path, ev, eid in all_evidences:
        if eid in seen:
            dupes.append({"first": seen[eid], "dup": (origin, path, ev.source, ev.article)})
        else:
            seen[eid] = (origin, path, ev.source, ev.article)

    dedup_evidences = [ev for origin, path, ev, eid in all_evidences]
    # 生产 BM25KnowledgeIndex 构造函数本身会在真实重复/空内容时 fail-fast；
    # 这里让它真实抛错而不是提前短路，以保证"0重复"是被生产代码本身验证过的事实。
    index = BM25KnowledgeIndex(dedup_evidences)

    by_article_sources = defaultdict(set)
    for origin, path, ev, eid in all_evidences:
        if ev.article:
            by_article_sources[ev.article].add(ev.source)
    cross_law_overlaps = {a: sorted(s) for a, s in by_article_sources.items() if len(s) > 1}

    source_stats = Counter(ev.source for origin, path, ev, eid in all_evidences)
    origin_stats = Counter(origin for origin, path, ev, eid in all_evidences)

    return {
        "loader": loader,
        "index": index,
        "evidences": dedup_evidences,
        "manifest_rows": manifest_rows,
        "duplicate_pairs": dupes,
        "cross_law_overlaps": cross_law_overlaps,
        "source_stats": dict(source_stats),
        "origin_stats": dict(origin_stats),
        "by_article_sources": {a: sorted(s) for a, s in by_article_sources.items()},
    }


# ---------------------------------------------------------------------------
# 2. 候选法律标签解析策略（显式声明的方法论，见 FULL_KB_BM25_EVALUATION.md 的"方法说明"节）
#
#   规则：
#   a) 按 "|" 切分 candidate_relevant_law 为若干 token。
#   b) token 若匹配 "第...条" 形式 -> 裸条号 token；否则 -> 法律/法规名 token。
#   c) 若该标签中存在且只存在一个法律/法规名 token，则该标签内所有裸条号 token 均归属该法律/法规。
#   d) 若该标签中不存在任何法律/法规名 token（全部是裸条号），则这些裸条号默认归属
#      《劳动合同法》—— 这是本项目的核心/默认法律（data/knowledge/ 下唯一的生产文件就是
#      劳动合同法.txt；上一轮单法知识库实验中，所有裸条号本来就只能指向劳动合同法）。
#      采用这一默认值是为了与历史轮次(A003/A004)保持口径一致、可比，而不是新发明的猜测。
#   e) 对于裸条号在 KB 中同一条号被"另一部法律"同时占用的情况（经交叉检查确认仅
#      第三十六/三十九/四十条 在《劳动合同法》与《劳动法》之间同号），默认策略(d)仍然
#      把它解析为《劳动合同法》对应条文 —— 不切换到另一法律，也不因为"另一法律同号条文
#      可能被BM25误召回"而把该样本标记为覆盖异常；该情况只在miss_analysis中作为
#      "cross_law_same_number_note"诊断性记录，不影响ground truth判定。
#   f) 本数据集450条候选标签中未出现任何显式写明《劳动争议调解仲裁法》的token，因此
#      仲裁法参考材料不会被当作任何样本的目标法条 —— 它只用于考察"隔离实验知识库扩容后，
#      是否会被BM25误召回到无关查询的TopK中"这一干扰性问题，不参与覆盖率/召回率的ground truth。
# ---------------------------------------------------------------------------
ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+条$")
KNOWN_LAW_NAMES = {"劳动法", "工伤保险条例", "职工带薪年休假条例", "劳动争议调解仲裁法"}
DEFAULT_LAW = "劳动合同法"


def resolve_candidate_law_tokens(candidate_relevant_law: str):
    """返回 list[{"law": str, "article": str, "raw_token": str}]"""
    tokens = [t.strip() for t in candidate_relevant_law.split("|") if t.strip()]
    law_name_tokens = [t for t in tokens if t in KNOWN_LAW_NAMES or (not ARTICLE_RE.match(t))]
    bare_number_tokens = [t for t in tokens if ARTICLE_RE.match(t)]
    unknown_tokens = [t for t in tokens if t not in KNOWN_LAW_NAMES and not ARTICLE_RE.match(t)]

    resolved = []
    if len(law_name_tokens) == 1:
        anchor_law = law_name_tokens[0]
        for a in bare_number_tokens:
            resolved.append({"law": anchor_law, "article": a, "raw_token": f"{a}|{anchor_law}"})
        # 该law_name token本身若不伴随任何裸条号（理论上本数据集未出现，防御性处理）：
        if not bare_number_tokens:
            resolved.append({"law": anchor_law, "article": None, "raw_token": anchor_law})
    elif len(law_name_tokens) == 0:
        for a in bare_number_tokens:
            resolved.append({"law": DEFAULT_LAW, "article": a, "raw_token": a})
    else:
        # 一个标签里出现 >=2 个法律名token：本数据集未观察到此情况；按"需人工登记，不静默跳过"处理
        resolved.append({"law": None, "article": None, "raw_token": candidate_relevant_law,
                          "unparseable": True, "reason": "multiple_law_name_tokens"})
    return resolved, unknown_tokens


def lookup_in_kb(law, article, by_article_sources):
    """返回 (in_kb: bool, matched_evidence_source_or_None, cross_law_same_number_sources)"""
    if law is None or article is None:
        return False, None, []
    sources_with_this_number = by_article_sources.get(article, [])
    in_kb = law in sources_with_this_number
    cross_law_note = [s for s in sources_with_this_number if s != law]
    return in_kb, (law if in_kb else None), cross_law_note


# ---------------------------------------------------------------------------
# 3. 检索与指标计算（复用上一轮run_bm25_450_and_50.py已验证的pattern，泛化到全量KB）
# ---------------------------------------------------------------------------

def run_one_query(retriever, query, k=CANDIDATE_K):
    t0 = time.perf_counter()
    evs = retriever.search_legal_knowledge(query, k=k)
    elapsed = time.perf_counter() - t0
    candidates = [{"source": e.source, "article": e.article, "score": e.metadata.get("score")} for e in evs]
    return candidates, elapsed


def score_against_relevant(candidates, relevant_pairs, in_kb_pairs, ks=FINAL_TOP_KS):
    cand_pairs_full = [(c["source"], c["article"]) for c in candidates]
    out = {}
    for k in ks:
        cand_pairs = set(cand_pairs_full[:k])
        hits = [p for p in relevant_pairs if p in cand_pairs]
        hits_in_kb_only = [p for p in hits if p in in_kb_pairs]
        recall = (len(hits) / len(relevant_pairs)) if relevant_pairs else None
        recall_in_kb_only = (len(hits_in_kb_only) / len(in_kb_pairs)) if in_kb_pairs else None
        rank = None
        for idx, p in enumerate(cand_pairs_full[:k], start=1):
            if p in relevant_pairs:
                rank = idx
                break
        mrr = (1.0 / rank) if rank else 0.0
        dcg = 0.0
        for idx, p in enumerate(cand_pairs_full[:k], start=1):
            if p in relevant_pairs:
                dcg += 1.0 / math.log2(idx + 1)
        ideal_hits = min(len(relevant_pairs), k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1)) if ideal_hits else 0.0
        ndcg = (dcg / idcg) if idcg else 0.0
        out[k] = {
            "recall_lensA_all_labels": recall,
            "recall_lensB_kb_covered_only": recall_in_kb_only,
            "mrr_contribution": mrr,
            "ndcg": ndcg,
            "hits": hits,
            "relevant_pairs_in_kb": in_kb_pairs,
            "relevant_pairs_not_in_kb": [p for p in relevant_pairs if p not in in_kb_pairs],
        }
    return out


def aggregate_metrics(records, ks=FINAL_TOP_KS):
    """records: list of dict with 'scores_by_k' (keyed by k -> metrics) and 'relevant_pairs','in_kb_pairs'."""
    agg = {}
    n = len(records)
    n_with_kb_target = sum(1 for r in records if r["in_kb_pairs"])
    for k in ks:
        recalls_a = [r["scores_by_k"][k]["recall_lensA_all_labels"] for r in records if r["scores_by_k"][k]["recall_lensA_all_labels"] is not None]
        recalls_b = [r["scores_by_k"][k]["recall_lensB_kb_covered_only"] for r in records if r["scores_by_k"][k]["recall_lensB_kb_covered_only"] is not None]
        mrrs = [r["scores_by_k"][k]["mrr_contribution"] for r in records]
        ndcgs = [r["scores_by_k"][k]["ndcg"] for r in records]
        agg[f"recall@{k}_lensA_all_labels"] = (sum(recalls_a) / len(recalls_a)) if recalls_a else None
        agg[f"recall@{k}_lensB_kb_covered_subset"] = (sum(recalls_b) / len(recalls_b)) if recalls_b else None
        agg[f"mrr@{k}"] = (sum(mrrs) / len(mrrs)) if mrrs else None
        agg[f"ndcg@{k}"] = (sum(ndcgs) / len(ndcgs)) if ndcgs else None
    agg["n_samples_total"] = n
    agg["n_samples_with_at_least_one_kb_covered_target"] = n_with_kb_target
    agg["n_samples_fully_outside_kb"] = n - n_with_kb_target
    return agg


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    kb = build_full_kb()
    index = kb["index"]
    retriever = LegalKnowledgeRetriever(knowledge_base=index, top_k=CANDIDATE_K)
    by_article_sources = kb["by_article_sources"]

    print("全量实验KB构建完成：Evidence count =", index.count())
    print("来源统计:", kb["source_stats"])
    print("去重重复项数:", len(kb["duplicate_pairs"]))
    print("同号跨法条文(交叉参考，不影响ground truth):", kb["cross_law_overlaps"])

    # ---------------- 450份新合同：candidate_labels_pending_review.csv ----------------
    with open(DATASET_ROOT / "source_450" / "candidate_labels_pending_review.csv", encoding="utf-8-sig", newline="") as f:
        new_label_rows = list(csv.DictReader(f))
    with open(DATASET_ROOT / "source_450" / "manifest_450.csv", encoding="utf-8-sig", newline="") as f:
        manifest_rows_450 = list(csv.DictReader(f))
    manifest_by_id = {r["contract_id"]: r for r in manifest_rows_450}

    rank_detail_rows = []
    miss_rows = []
    coverage_audit_rows = []
    new_records_by_split = defaultdict(list)
    unparseable_registry = []

    for r in new_label_rows:
        resolved, unknown = resolve_candidate_law_tokens(r["candidate_relevant_law"])
        relevant_pairs = []
        in_kb_pairs = []
        token_audit = []
        for item in resolved:
            if item.get("unparseable"):
                unparseable_registry.append({"contract_id": r["contract_id"], "query_id": r["query_id"],
                                              "candidate_relevant_law": r["candidate_relevant_law"],
                                              "reason": item["reason"]})
                continue
            law, article = item["law"], item["article"]
            if article is None:
                # 纯法规名token（本数据集未观察到），记为该法规整体不在KB中可定位的具体条文
                token_audit.append({"law": law, "article": None, "in_kb": law in kb["source_stats"],
                                     "cross_law_same_number_sources": []})
                continue
            pair = (law, article)
            relevant_pairs.append(pair)
            in_kb, matched_source, cross_note = lookup_in_kb(law, article, by_article_sources)
            if in_kb:
                in_kb_pairs.append(pair)
            token_audit.append({"law": law, "article": article, "in_kb": in_kb,
                                 "cross_law_same_number_sources": cross_note})

        candidates, elapsed = run_one_query(retriever, r["query_text"], k=CANDIDATE_K)
        scores = score_against_relevant(candidates, relevant_pairs, in_kb_pairs)

        m = manifest_by_id.get(r["contract_id"], {})
        split = r["dataset_split"]
        rec = {
            "contract_id": r["contract_id"], "query_id": r["query_id"],
            "relevant_pairs": relevant_pairs, "in_kb_pairs": in_kb_pairs,
            "candidates_top20": candidates, "scores_by_k": scores,
        }
        new_records_by_split[split].append(rec)
        new_records_by_split["__all__"].append(rec)

        # coverage_audit row (one row per contract_id+query_id, with token-level detail)
        coverage_audit_rows.append({
            "dataset": "new_450", "contract_id": r["contract_id"], "query_id": r["query_id"],
            "dataset_split": split, "scenario_id": r["scenario_id"],
            "scenario_name": m.get("scenario_name", ""),
            "candidate_relevant_law_raw": r["candidate_relevant_law"],
            "resolved_tokens": json.dumps(token_audit, ensure_ascii=False),
            "any_target_in_kb": bool(in_kb_pairs),
            "all_targets_in_kb": bool(relevant_pairs) and len(in_kb_pairs) == len(relevant_pairs),
            "n_targets_total": len(relevant_pairs), "n_targets_in_kb": len(in_kb_pairs),
        })

        # rank_detail + miss rows for each K
        cand_pairs_full = [(c["source"], c["article"]) for c in candidates]
        for pair in relevant_pairs:
            try:
                rank = cand_pairs_full.index(pair) + 1
                score_val = candidates[rank - 1]["score"]
            except ValueError:
                rank = None
                score_val = None
            in_kb_flag = pair in in_kb_pairs
            rank_detail_rows.append({
                "dataset": "new_450", "contract_id": r["contract_id"], "query_id": r["query_id"],
                "dataset_split": split, "target_law": pair[0], "target_article": pair[1],
                "target_in_kb": in_kb_flag, "actual_rank": rank, "actual_score": score_val,
                "top1_source": candidates[0]["source"] if candidates else None,
                "top1_article": candidates[0]["article"] if candidates else None,
            })
            for k in FINAL_TOP_KS:
                hit = rank is not None and rank <= k
                if not hit:
                    if not in_kb_flag:
                        reason = "target_article_not_in_kb"
                    elif rank is None:
                        reason = "in_kb_but_not_in_top20_candidate_pool"
                    else:
                        reason = f"in_kb_rank_{rank}_exceeds_topK_{k}"
                    miss_rows.append({
                        "dataset": "new_450", "contract_id": r["contract_id"], "query_id": r["query_id"],
                        "dataset_split": split, "topk": k, "target_law": pair[0], "target_article": pair[1],
                        "target_in_kb": in_kb_flag, "actual_rank": rank, "miss_reason": reason,
                    })

    # ---------------- 现有50份：188条可评估样本 ----------------
    old_data = json.loads(OLD_EVAL_SAMPLES.read_text(encoding="utf-8"))
    old_samples = [s for s in old_data["samples"] if s.get("evaluable")]
    assert len(old_samples) == old_data["evaluable_count"], "old_50 evaluable_count mismatch — 数据已变化，需重新审计"

    old_records = []
    for s in old_samples:
        relevant_pairs = [(p["source"], p["article"]) for p in s["relevant"]]
        in_kb_pairs = []
        for pair in relevant_pairs:
            in_kb, _, cross_note = lookup_in_kb(pair[0], pair[1], by_article_sources)
            if in_kb:
                in_kb_pairs.append(pair)
        candidates, elapsed = run_one_query(retriever, s["query"], k=CANDIDATE_K)
        scores = score_against_relevant(candidates, relevant_pairs, in_kb_pairs)
        old_records.append({
            "sample_id": s["sample_id"], "relevant_pairs": relevant_pairs, "in_kb_pairs": in_kb_pairs,
            "candidates_top20": candidates, "scores_by_k": scores,
        })

        cand_pairs_full = [(c["source"], c["article"]) for c in candidates]
        for pair in relevant_pairs:
            try:
                rank = cand_pairs_full.index(pair) + 1
                score_val = candidates[rank - 1]["score"]
            except ValueError:
                rank = None
                score_val = None
            in_kb_flag = pair in in_kb_pairs
            rank_detail_rows.append({
                "dataset": "old_50_sample188", "contract_id": s.get("contract_sample_id"), "query_id": s["sample_id"],
                "dataset_split": "n/a", "target_law": pair[0], "target_article": pair[1],
                "target_in_kb": in_kb_flag, "actual_rank": rank, "actual_score": score_val,
                "top1_source": candidates[0]["source"] if candidates else None,
                "top1_article": candidates[0]["article"] if candidates else None,
            })
            for k in FINAL_TOP_KS:
                hit = rank is not None and rank <= k
                if not hit:
                    reason = ("target_article_not_in_kb" if not in_kb_flag else
                              ("in_kb_but_not_in_top20_candidate_pool" if rank is None else
                               f"in_kb_rank_{rank}_exceeds_topK_{k}"))
                    miss_rows.append({
                        "dataset": "old_50_sample188", "contract_id": s.get("contract_sample_id"), "query_id": s["sample_id"],
                        "dataset_split": "n/a", "topk": k, "target_law": pair[0], "target_article": pair[1],
                        "target_in_kb": in_kb_flag, "actual_rank": rank, "miss_reason": reason,
                    })

    # ---------------- 指标聚合 ----------------
    metrics = {
        "new_450_development_n360": aggregate_metrics(new_records_by_split["development"]),
        "new_450_final_test_n90": aggregate_metrics(new_records_by_split["final_test"]),
        "new_450_combined_n450": aggregate_metrics(new_records_by_split["__all__"]),
        "old_50_sample188": aggregate_metrics(old_records),
        "lensC_note": "以上全部指标均依赖 candidate_labels_pending_review.csv / retrieval_eval_samples.json 中的"
                       "候选相关法条标签，这些标签尚未经有法律资格人员最终确认（verification_status 字段），"
                       "不可作为gold standard直接使用，仅作研究性参考。",
    }

    # ---------------- 工作地点单方变更场景（第26/35条）专项 ----------------
    workplace_records = [rec for rec in new_records_by_split["__all__"]
                         if any(a == "第二十六条" or a == "第三十五条" for (_, a) in rec["relevant_pairs"])]
    workplace_detail = []
    for rec in workplace_records:
        for k in FINAL_TOP_KS:
            workplace_detail.append({
                "contract_id": rec["contract_id"], "query_id": rec["query_id"], "topk": k,
                "recall_lensA": rec["scores_by_k"][k]["recall_lensA_all_labels"],
                "hits": rec["scores_by_k"][k]["hits"],
            })

    # ---------------- 写出产物文件 ----------------
    def write_csv(path, rows, fieldnames):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in rows:
                w.writerow(row)

    # knowledge_manifest.csv
    write_csv(OUT_DIR / "knowledge_manifest.csv", kb["manifest_rows"],
               fieldnames=["origin", "origin_file", "origin_file_sha256", "source", "article", "part",
                           "content_length", "content_sha256", "evidence_id"])

    # knowledge_coverage_audit.csv
    write_csv(OUT_DIR / "knowledge_coverage_audit.csv", coverage_audit_rows,
               fieldnames=["dataset", "contract_id", "query_id", "dataset_split", "scenario_id", "scenario_name",
                           "candidate_relevant_law_raw", "resolved_tokens", "any_target_in_kb", "all_targets_in_kb",
                           "n_targets_total", "n_targets_in_kb"])

    # retrieval_rank_detail.csv
    write_csv(OUT_DIR / "retrieval_rank_detail.csv", rank_detail_rows,
               fieldnames=["dataset", "contract_id", "query_id", "dataset_split", "target_law", "target_article",
                           "target_in_kb", "actual_rank", "actual_score", "top1_source", "top1_article"])

    # miss_analysis.csv
    write_csv(OUT_DIR / "miss_analysis.csv", miss_rows,
               fieldnames=["dataset", "contract_id", "query_id", "dataset_split", "topk", "target_law",
                           "target_article", "target_in_kb", "actual_rank", "miss_reason"])

    # metrics.json
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    # run_metadata.json
    run_metadata = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kb_evidence_count": index.count(),
        "kb_source_stats": kb["source_stats"],
        "kb_origin_stats": kb["origin_stats"],
        "kb_duplicate_pairs_found": len(kb["duplicate_pairs"]),
        "kb_cross_law_same_number_overlaps": kb["cross_law_overlaps"],
        "kb_source_files": [{"origin": o, "path": str(p), "law_name": n} for o, p, n in KB_SOURCE_FILES],
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "bm25_params": {"k1": 1.5, "b": 0.75, "tokenizer": "char_bigram (production rag.bm25_index.char_bigram_tokenizer)"},
        "tie_break_rule": "生产 BM25KnowledgeIndex.similarity_search 按 (-score, original_index) 排序，分数相同时原始索引更小者排前",
        "label_resolution_policy": "见脚本顶部注释：法规名token显式锚定；无法规名token默认归属《劳动合同法》；"
                                     "同号跨法条文仅作诊断性记录，不改变ground truth判定",
        "unparseable_labels": unparseable_registry,
        "dataset_split_counts": {k_: len(v) for k_, v in new_records_by_split.items() if k_ != "__all__"},
        "old_50_evaluable_count": len(old_samples),
        "environment": {
            "python_version": platform.python_version(),
            "note": "沙箱内使用轻量占位 langchain_core/langchain_text_splitters/langchain_huggingface 模块"
                    "（已逐源文件以生产 _ARTICLE_RE 验证最长条文块长度远小于chunk_size=500，"
                    "RecursiveCharacterTextSplitter 占位的 split_text 从未被真实调用），"
                    "rag.bm25_index / rag.knowledge_loader / rag.retriever / document / schemas 为设备原始真实源码未改动。",
        },
    }
    (OUT_DIR / "run_metadata.json").write_text(json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    # workplace relocation detail (附加产物，供报告引用)
    (OUT_DIR / "workplace_relocation_detail.json").write_text(
        json.dumps(workplace_detail, ensure_ascii=False, indent=2), encoding="utf-8")

    print("全部产出文件已写入:", OUT_DIR)
    print("metrics summary (development):", json.dumps(metrics["new_450_development_n360"], ensure_ascii=False))
    print("metrics summary (final_test):", json.dumps(metrics["new_450_final_test_n90"], ensure_ascii=False))
    print("metrics summary (old_50_188):", json.dumps(metrics["old_50_sample188"], ensure_ascii=False))

    return {
        "kb": kb, "metrics": metrics, "run_metadata": run_metadata,
        "n_rank_detail_rows": len(rank_detail_rows), "n_miss_rows": len(miss_rows),
        "n_coverage_audit_rows": len(coverage_audit_rows),
        "workplace_detail": workplace_detail,
    }


if __name__ == "__main__":
    main()
