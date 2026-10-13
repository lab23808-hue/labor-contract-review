# -*- coding: utf-8 -*-
"""
experiment_kb/scripts/bm25_kb_growth_diagnosis.py

本轮实验："26/37/44条知识库的BM25排名退化归因与方案对比"
严格只用development划分做方案选择；final_test全程不参与任何决策。
调用生产 rag.bm25_index.BM25KnowledgeIndex（未改动，char_bigram, k1=1.5,b=0.75）。
"""
from __future__ import annotations
import csv, json, hashlib, math, re, sys, os, time, platform
from pathlib import Path
from collections import defaultdict, Counter

PROJECT_ROOT = Path(os.environ.get("LCR_PROJECT_ROOT", r"C:\Javase\pythonproject\labor_contract_review"))
SANDBOX_SRC_ROOT = Path("/home/claude/work/labor_contract_review")
DATASET_ROOT = PROJECT_ROOT / "experiment_kb" / "datasets" / "contract_eval_500_20261013"
OUT_DIR = PROJECT_ROOT / "experiment_kb" / "results" / "bm25_kb_growth_diagnosis_20261013"

sys.path.insert(0, str(PROJECT_ROOT))
SANDBOX_MODE = False
try:
    from rag.knowledge_loader import KnowledgeLoader
    from rag.bm25_index import BM25KnowledgeIndex, char_bigram_tokenizer
    from rag.retriever import LegalKnowledgeRetriever
    import rag.database as real_db
except ModuleNotFoundError as e:
    if str(SANDBOX_SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SANDBOX_SRC_ROOT))
    import conftest_fakes  # noqa: F401
    from rag.knowledge_loader import KnowledgeLoader
    from rag.bm25_index import BM25KnowledgeIndex, char_bigram_tokenizer
    from rag.retriever import LegalKnowledgeRetriever
    import rag.database as real_db
    SANDBOX_MODE = True

CANDIDATE_K = 20
FINAL_TOP_KS = [5, 10, 20]

KB_ALL_SOURCE_FILES = [
    ("production", PROJECT_ROOT / "data" / "knowledge" / "劳动合同法.txt", "劳动合同法"),
    ("working_new", PROJECT_ROOT / "experiment_kb" / "working" / "data" / "knowledge" / "LAW_01_劳动合同法_第五十条.txt", "劳动合同法"),
    ("working_new", PROJECT_ROOT / "experiment_kb" / "working" / "data" / "knowledge" / "LAW_02_劳动法_第三十六条至第四十五条.txt", "劳动法"),
    ("reference_only", PROJECT_ROOT / "experiment_kb" / "reference_only" / "仲裁法_第十条至第十六条_参考材料.txt", "劳动争议调解仲裁法"),
]
KB_VERSIONS = {
    "kb26": KB_ALL_SOURCE_FILES[0:1],
    "kb37": KB_ALL_SOURCE_FILES[0:3],
    "kb44": KB_ALL_SOURCE_FILES[0:4],
}

ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+条$")
KNOWN_LAW_NAMES = {"劳动法", "工伤保险条例", "职工带薪年休假条例", "劳动争议调解仲裁法"}
DEFAULT_LAW = "劳动合同法"


def resolve_candidate_law_tokens(candidate_relevant_law: str):
    tokens = [t.strip() for t in candidate_relevant_law.split("|") if t.strip()]
    law_name_tokens = [t for t in tokens if not ARTICLE_RE.match(t)]
    bare_number_tokens = [t for t in tokens if ARTICLE_RE.match(t)]
    resolved = []
    if len(law_name_tokens) == 1:
        anchor_law = law_name_tokens[0]
        for a in bare_number_tokens:
            resolved.append({"law": anchor_law, "article": a})
        if not bare_number_tokens:
            resolved.append({"law": anchor_law, "article": None})
    elif len(law_name_tokens) == 0:
        for a in bare_number_tokens:
            resolved.append({"law": DEFAULT_LAW, "article": a})
    else:
        resolved.append({"law": None, "article": None, "unparseable": True})
    return resolved


def build_kb(version_key):
    loader = KnowledgeLoader(knowledge_base=real_db.ChromaKnowledgeBase.__new__(real_db.ChromaKnowledgeBase))
    all_evidences = []
    manifest_rows = []
    for origin, path, law_name in KB_VERSIONS[version_key]:
        text = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        evs = loader.load_file(str(path), source=law_name)
        for ev in evs:
            eid = KnowledgeLoader._evidence_id(ev)
            all_evidences.append((origin, ev, eid))
            manifest_rows.append({
                "kb_version": version_key, "origin": origin, "origin_file": str(path),
                "origin_file_sha256": file_hash, "source": ev.source, "article": ev.article,
                "part": ev.metadata.get("part", ""), "content_length": len(ev.content),
                "content_sha256": hashlib.sha256(ev.content.encode("utf-8")).hexdigest(),
                "evidence_id": eid,
            })
    evidences = [ev for origin, ev, eid in all_evidences]
    index = BM25KnowledgeIndex(evidences)  # fail-fast real dedup/empty-content check
    evidence_ids = set(eid for origin, ev, eid in all_evidences)
    by_article_sources = defaultdict(set)
    for origin, ev, eid in all_evidences:
        if ev.article:
            by_article_sources[ev.article].add(ev.source)
    doc_lengths = [len(char_bigram_tokenizer(ev.content)) for ev in evidences]
    avg_doc_len = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0
    evidence_set_hash = hashlib.sha256("|".join(sorted(evidence_ids)).encode("utf-8")).hexdigest()
    return {
        "version": version_key, "loader": loader, "index": index, "evidences": evidences,
        "manifest_rows": manifest_rows, "evidence_ids": evidence_ids,
        "by_article_sources": {a: sorted(s) for a, s in by_article_sources.items()},
        "n_docs": len(evidences), "avg_doc_len_bigrams": avg_doc_len,
        "evidence_set_hash": evidence_set_hash,
        "retriever": LegalKnowledgeRetriever(knowledge_base=index, top_k=CANDIDATE_K),
    }


def run_query(kb, query_text, k=CANDIDATE_K):
    t0 = time.perf_counter()
    evs = kb["retriever"].search_legal_knowledge(query_text, k=k)
    elapsed = time.perf_counter() - t0
    return [{"source": e.source, "article": e.article, "score": e.metadata.get("score")} for e in evs], elapsed


def score_metrics(candidates, relevant_pairs, in_kb_pairs, ks=FINAL_TOP_KS):
    cand_full = [(c["source"], c["article"]) for c in candidates]
    out = {}
    for k in ks:
        window = set(cand_full[:k])
        hits = [p for p in relevant_pairs if p in window]
        hits_kb = [p for p in hits if p in in_kb_pairs]
        recallA = (len(hits) / len(relevant_pairs)) if relevant_pairs else None
        recallB = (len(hits_kb) / len(in_kb_pairs)) if in_kb_pairs else None
        rank = None
        for idx, p in enumerate(cand_full[:k], start=1):
            if p in relevant_pairs:
                rank = idx; break
        mrr = (1.0 / rank) if rank else 0.0
        dcg = sum(1.0 / math.log2(i + 1) for i, p in enumerate(cand_full[:k], start=1) if p in relevant_pairs)
        ideal = min(len(relevant_pairs), k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal + 1)) if ideal else 0.0
        ndcg = (dcg / idcg) if idcg else 0.0
        out[k] = {"recallA": recallA, "recallB": recallB, "mrr": mrr, "ndcg": ndcg, "hits": hits}
    return out


def aggregate(records, ks=FINAL_TOP_KS):
    agg = {}
    for k in ks:
        ra = [r["scores_by_k"][k]["recallA"] for r in records if r["scores_by_k"][k]["recallA"] is not None]
        rb = [r["scores_by_k"][k]["recallB"] for r in records if r["scores_by_k"][k]["recallB"] is not None]
        mrr = [r["scores_by_k"][k]["mrr"] for r in records]
        ndcg = [r["scores_by_k"][k]["ndcg"] for r in records]
        agg[f"recall@{k}_lensA"] = sum(ra) / len(ra) if ra else None
        agg[f"recall@{k}_lensB"] = sum(rb) / len(rb) if rb else None
        agg[f"mrr@{k}"] = sum(mrr) / len(mrr) if mrr else None
        agg[f"ndcg@{k}"] = sum(ndcg) / len(ndcg) if ndcg else None
    agg["n"] = len(records)
    return agg


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- 1. 构建三版本KB并验证子集关系 ----------
    kbs = {v: build_kb(v) for v in ["kb26", "kb37", "kb44"]}
    subset_26_in_37 = kbs["kb26"]["evidence_ids"].issubset(kbs["kb37"]["evidence_ids"])
    subset_37_in_44 = kbs["kb37"]["evidence_ids"].issubset(kbs["kb44"]["evidence_ids"])
    print(f"kb26={kbs['kb26']['n_docs']} kb37={kbs['kb37']['n_docs']} kb44={kbs['kb44']['n_docs']}")
    print(f"26⊆37: {subset_26_in_37}  37⊆44: {subset_37_in_44}")
    assert subset_26_in_37 and subset_37_in_44, "版本嵌套关系校验失败——必须先修复才能继续"

    all_manifest_rows = []
    for v in ["kb26", "kb37", "kb44"]:
        all_manifest_rows.extend(kbs[v]["manifest_rows"])
    with open(OUT_DIR / "kb_version_manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kb_version", "origin", "origin_file", "origin_file_sha256", "source",
                                           "article", "part", "content_length", "content_sha256", "evidence_id"])
        w.writeheader()
        for row in all_manifest_rows:
            w.writerow(row)

    # ---------- 2. development划分query ----------
    with open(DATASET_ROOT / "source_450" / "candidate_labels_pending_review.csv", encoding="utf-8-sig", newline="") as f:
        label_rows = [r for r in csv.DictReader(f) if r["dataset_split"] == "development"]
    with open(DATASET_ROOT / "source_450" / "manifest_450.csv", encoding="utf-8-sig", newline="") as f:
        manifest_450 = {r["contract_id"]: r for r in csv.DictReader(f)}
    print(f"development query数: {len(label_rows)}")

    # 预解析每条query的候选法条token（与KB版本无关，只做一次）
    for r in label_rows:
        r["_resolved"] = resolve_candidate_law_tokens(r["candidate_relevant_law"])

    # ---------- 3. 三版本分别检索 + lensA/B 指标 + rank_change_detail ----------
    version_records = {}  # version -> list of per-query record (with per-target rank/score)
    rank_change_rows = []
    per_version_candidates_cache = {}  # (version) -> {(contract_id,query_id): candidates}

    for v in ["kb26", "kb37", "kb44"]:
        kb = kbs[v]
        records = []
        cand_cache = {}
        for r in label_rows:
            candidates, elapsed = run_query(kb, r["query_text"], k=CANDIDATE_K)
            cand_cache[(r["contract_id"], r["query_id"])] = candidates
            relevant_pairs, in_kb_pairs = [], []
            for item in r["_resolved"]:
                if item.get("unparseable") or item["article"] is None:
                    continue
                pair = (item["law"], item["article"])
                relevant_pairs.append(pair)
                if item["article"] in kb["by_article_sources"] and item["law"] in kb["by_article_sources"][item["article"]]:
                    in_kb_pairs.append(pair)
            scores = score_metrics(candidates, relevant_pairs, in_kb_pairs)
            records.append({"contract_id": r["contract_id"], "query_id": r["query_id"],
                             "relevant_pairs": relevant_pairs, "in_kb_pairs": in_kb_pairs,
                             "candidates": candidates, "scores_by_k": scores, "elapsed": elapsed})
        version_records[v] = records
        per_version_candidates_cache[v] = cand_cache
        print(f"{v} done, n={len(records)}")

    # 共同覆盖子集：目标在kb26中即存在（因26⊆37⊆44，这是最严格的子集，三版本都有该目标）
    def common_covered_query_target_pairs():
        pairs = set()
        for r in label_rows:
            for item in r["_resolved"]:
                if item.get("unparseable") or item["article"] is None:
                    continue
                pair = (item["law"], item["article"])
                if item["article"] in kbs["kb26"]["by_article_sources"] and item["law"] in kbs["kb26"]["by_article_sources"][item["article"]]:
                    pairs.add((r["contract_id"], r["query_id"], pair))
        return pairs

    common_set = common_covered_query_target_pairs()
    print(f"三版本共同覆盖的(query,target)数: {len(common_set)}")

    # rank_change_detail.csv: 逐query逐target在三版本中的排名/分数
    by_cid_qid = {(r["contract_id"], r["query_id"]): r for r in label_rows}
    all_targets = set()
    for r in label_rows:
        for item in r["_resolved"]:
            if item.get("unparseable") or item["article"] is None:
                continue
            all_targets.add((r["contract_id"], r["query_id"], item["law"], item["article"]))

    for contract_id, query_id, law, article in sorted(all_targets):
        row = {"contract_id": contract_id, "query_id": query_id, "target_law": law, "target_article": article,
               "in_common_covered_subset": (contract_id, query_id, (law, article)) in common_set}
        for v in ["kb26", "kb37", "kb44"]:
            cands = per_version_candidates_cache[v][(contract_id, query_id)]
            cand_pairs = [(c["source"], c["article"]) for c in cands]
            in_kb = article in kbs[v]["by_article_sources"] and law in kbs[v]["by_article_sources"][article]
            try:
                rank = cand_pairs.index((law, article)) + 1
                score = cands[rank - 1]["score"]
            except ValueError:
                rank, score = None, None
            row[f"{v}_in_kb"] = in_kb
            row[f"{v}_rank"] = rank
            row[f"{v}_score"] = score
        rank_change_rows.append(row)

    with open(OUT_DIR / "rank_change_detail.csv", "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["contract_id", "query_id", "target_law", "target_article", "in_common_covered_subset",
                      "kb26_in_kb", "kb26_rank", "kb26_score", "kb37_in_kb", "kb37_rank", "kb37_score",
                      "kb44_in_kb", "kb44_rank", "kb44_score"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rank_change_rows:
            w.writerow(row)

    # ---------- 4. kb_growth_competitor_analysis: 新增文档挤出TopK ----------
    competitor_rows = []
    for row in rank_change_rows:
        r26, r37, r44 = row["kb26_rank"], row["kb37_rank"], row["kb44_rank"]
        if not row["kb26_in_kb"]:
            continue  # 26版本里本来就没有，不是"挤出"问题
        # 26->37 是否恶化 (排名变差或掉出候选池)
        for transition, from_v, to_v, from_rank, to_rank in [
            ("26to37", "kb26", "kb37", r26, r37), ("37to44", "kb37", "kb44", r37, r44),
        ]:
            worsened = (from_rank is not None and (to_rank is None or to_rank > from_rank))
            if not worsened:
                continue
            cid, qid = row["contract_id"], row["query_id"]
            to_cands = per_version_candidates_cache[to_v][(cid, qid)]
            from_cands = per_version_candidates_cache[from_v][(cid, qid)]
            from_pairs = set((c["source"], c["article"]) for c in from_cands)
            cutoff = to_rank if to_rank else len(to_cands) + 1
            new_docs_ahead = [c for c in to_cands[:cutoff - 1] if (c["source"], c["article"]) not in from_pairs]
            competitor_rows.append({
                "contract_id": cid, "query_id": qid, "target_law": row["target_law"], "target_article": row["target_article"],
                "transition": transition, "from_rank": from_rank, "to_rank": to_rank,
                "n_new_docs_ranked_ahead": len(new_docs_ahead),
                "new_docs_ranked_ahead": json.dumps(new_docs_ahead, ensure_ascii=False),
            })

    with open(OUT_DIR / "kb_growth_competitor_analysis.csv", "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["contract_id", "query_id", "target_law", "target_article", "transition", "from_rank",
                      "to_rank", "n_new_docs_ranked_ahead", "new_docs_ranked_ahead"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in competitor_rows:
            w.writerow(row)

    # ---------- 5. IDF/corpus统计对比（直接用生产tokenizer真实计算） ----------
    def corpus_stats(kb):
        df = Counter()
        N = len(kb["evidences"])
        for ev in kb["evidences"]:
            toks = set(char_bigram_tokenizer(ev.content))
            for t in toks:
                df[t] += 1
        return {"N": N, "avg_doc_len_bigrams": kb["avg_doc_len_bigrams"], "vocab_size": len(df),
                "df_counter": df}

    stats = {v: corpus_stats(kbs[v]) for v in ["kb26", "kb37", "kb44"]}

    # ---------- 6. metrics聚合 (develpment, 三版本, lensA/B + common子集) ----------
    def common_subset_records(v):
        out = []
        for rec in version_records[v]:
            filt_targets = [p for p in rec["relevant_pairs"] if (rec["contract_id"], rec["query_id"], p) in common_set]
            if not filt_targets:
                continue
            scores = score_metrics(rec["candidates"], filt_targets, filt_targets)  # 在common子集里，relevant==in_kb(kb26口径)
            out.append({"scores_by_k": scores})
        return out

    metrics_out = {}
    for v in ["kb26", "kb37", "kb44"]:
        metrics_out[v] = {
            "all_dev_lensA_B": aggregate(version_records[v]),
            "common_covered_subset": aggregate(common_subset_records(v)),
        }

    with open(OUT_DIR / "BM25_KB_GROWTH_DIAGNOSIS_20261013.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kb_versions": {v: {"n_docs": kbs[v]["n_docs"], "avg_doc_len_bigrams": kbs[v]["avg_doc_len_bigrams"],
                                 "vocab_size": stats[v]["vocab_size"], "evidence_set_hash": kbs[v]["evidence_set_hash"]}
                            for v in ["kb26", "kb37", "kb44"]},
            "subset_check": {"26_in_37": subset_26_in_37, "37_in_44": subset_37_in_44},
            "n_dev_queries": len(label_rows),
            "n_common_covered_query_target_pairs": len(common_set),
            "metrics": metrics_out,
            "environment": {"python_version": platform.python_version(), "sandbox_mode": SANDBOX_MODE,
                             "bm25_params": {"k1": 1.5, "b": 0.75, "tokenizer": "char_bigram"}, "candidate_k": CANDIDATE_K},
        }, f, ensure_ascii=False, indent=2)

    print(json.dumps({v: metrics_out[v]["all_dev_lensA_B"] for v in ["kb26", "kb37", "kb44"]}, ensure_ascii=False, indent=2))

    return {
        "kbs": kbs, "stats": stats, "rank_change_rows": rank_change_rows, "competitor_rows": competitor_rows,
        "version_records": version_records, "per_version_candidates_cache": per_version_candidates_cache,
        "label_rows": label_rows, "common_set": common_set, "metrics_out": metrics_out,
        "manifest_450": manifest_450,
    }


if __name__ == "__main__":
    main()
