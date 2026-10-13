# -*- coding: utf-8 -*-
"""Part 2: 第26/35条专项 + 方案A/B/C对照。复用 part1(kb_growth_diagnosis.py) 的构建结果。"""
import sys, csv, json, math, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kb_growth_diagnosis as p1

OUT_DIR = p1.OUT_DIR


def main():
    ctx = p1.main()
    kbs = ctx["kbs"]
    label_rows = ctx["label_rows"]
    manifest_450 = ctx["manifest_450"]
    per_version_candidates_cache = ctx["per_version_candidates_cache"]
    rank_change_rows = ctx["rank_change_rows"]

    # ============== 五、第26/35条专项(15个工作地点场景) ==============
    wp_ids = set(cid for cid, r in manifest_450.items() if r["scenario_id"] == "workplace_unilateral")
    wp_rows = [r for r in label_rows if r["contract_id"] in wp_ids]
    print(f"工作地点场景(development内) n={len(wp_rows)}")

    wp_detail = []
    rank_lookup = {(r["contract_id"], r["query_id"], r["target_law"], r["target_article"]): r
                   for r in rank_change_rows}
    for r in wp_rows:
        for art in ["第二十六条", "第三十五条"]:
            key = (r["contract_id"], r["query_id"], "劳动合同法", art)
            rc = rank_lookup.get(key)
            if rc is None:
                continue
            wp_detail.append({
                "contract_id": r["contract_id"], "query_id": r["query_id"], "query_text": r["query_text"],
                "target_clause_title": r["target_clause_title"],
                "candidate_relevant_law_raw": r["candidate_relevant_law"],
                "verification_status": r["verification_status"],
                "target_article": art,
                "kb26_in_kb": rc["kb26_in_kb"], "kb26_rank": rc["kb26_rank"], "kb26_score": rc["kb26_score"],
                "kb37_in_kb": rc["kb37_in_kb"], "kb37_rank": rc["kb37_rank"], "kb37_score": rc["kb37_score"],
                "kb44_in_kb": rc["kb44_in_kb"], "kb44_rank": rc["kb44_rank"], "kb44_score": rc["kb44_score"],
                "hit_top5_kb26": rc["kb26_rank"] is not None and int(rc["kb26_rank"]) <= 5,
                "hit_top10_kb26": rc["kb26_rank"] is not None and int(rc["kb26_rank"]) <= 10,
                "hit_top20_kb26": rc["kb26_rank"] is not None and int(rc["kb26_rank"]) <= 20,
                "hit_top5_kb44": rc["kb44_rank"] is not None and int(rc["kb44_rank"]) <= 5,
                "hit_top10_kb44": rc["kb44_rank"] is not None and int(rc["kb44_rank"]) <= 10,
                "hit_top20_kb44": rc["kb44_rank"] is not None and int(rc["kb44_rank"]) <= 20,
            })

    with open(OUT_DIR / "workplace_article_26_35_analysis.csv", "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = list(wp_detail[0].keys()) if wp_detail else []
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in wp_detail:
            w.writerow(row)

    n26 = len(set(r["contract_id"] for r in wp_detail if r["target_article"] == "第二十六条"))
    miss26_kb26 = sum(1 for r in wp_detail if r["target_article"] == "第二十六条" and not r["hit_top20_kb26"])
    miss26_kb44 = sum(1 for r in wp_detail if r["target_article"] == "第二十六条" and not r["hit_top20_kb44"])
    miss35_kb26 = sum(1 for r in wp_detail if r["target_article"] == "第三十五条" and not r["hit_top20_kb26"])
    miss35_kb44 = sum(1 for r in wp_detail if r["target_article"] == "第三十五条" and not r["hit_top20_kb44"])
    print(f"第26条miss@20: kb26={miss26_kb26} kb44={miss26_kb44} (n={n26})")
    print(f"第35条miss@20: kb26={miss35_kb26} kb44={miss35_kb44} (n={n26})")

    # ============== 六、方案A/B/C对照(development only) ==============
    # 方案A：全局BM25（即kb44，已有结果）
    strategy_A_records = ctx["version_records"]["kb44"]

    # 方案B：按法律来源建立独立BM25索引，round-robin合并候选（不直接比较跨索引原始分数）
    from rag.bm25_index import BM25KnowledgeIndex
    from rag.retriever import LegalKnowledgeRetriever
    import rag.database as real_db

    sources_in_kb44 = sorted(set(ev.source for ev in kbs["kb44"]["evidences"]))
    sub_retrievers = {}
    for src in sources_in_kb44:
        evs = [ev for ev in kbs["kb44"]["evidences"] if ev.source == src]
        idx = BM25KnowledgeIndex(evs)
        sub_retrievers[src] = LegalKnowledgeRetriever(knowledge_base=idx, top_k=p1.CANDIDATE_K)
    print("方案B子索引:", {k: len(v2) for k, v2 in [(s, [e for e in kbs['kb44']['evidences'] if e.source == s]) for s in sources_in_kb44]})

    def strategy_B_query(query_text, k=p1.CANDIDATE_K):
        t0 = time.perf_counter()
        per_source_results = {}
        for src, retr in sub_retrievers.items():
            evs = retr.search_legal_knowledge(query_text, k=k)
            per_source_results[src] = [{"source": e.source, "article": e.article, "score": e.metadata.get("score")} for e in evs]
        # 合并方式：按各子索引内部排名轮询交替(round-robin)，不直接比较不同索引的原始BM25分数
        merged = []
        maxlen = max(len(v) for v in per_source_results.values()) if per_source_results else 0
        for i in range(maxlen):
            for src in sources_in_kb44:
                lst = per_source_results[src]
                if i < len(lst):
                    merged.append(lst[i])
        elapsed = time.perf_counter() - t0
        return merged[:k], elapsed

    # 方案C：基于query内容的法律领域路由（关键词规则，仅用query文本，不读取标签；规则本身在development集上制定）
    # 规则制定依据：劳动法(working新增36-45条)覆盖的是工时/休息休假/加班/年休假主题；
    # 仲裁法(reference_only)覆盖的是调解/仲裁申请/支付令程序主题；其余默认路由到劳动合同法(+劳动法，因为
    # 劳动合同法本身也覆盖解除/经济补偿等主流场景，保留其为默认兜底，避免路由错误导致目标彻底不可及)。
    ROUTE_KEYWORDS = {
        "劳动法": ["工时", "工作时间", "休息日", "加班", "年休假", "带薪年休假", "综合计算工时", "不定时工作制", "法定假期", "休假"],
        "劳动争议调解仲裁法": ["仲裁", "调解", "支付令", "劳动争议"],
    }

    def route_query(query_text):
        matched = [law for law, kws in ROUTE_KEYWORDS.items() if any(kw in query_text for kw in kws)]
        # 默认总是包含劳动合同法（兜底，覆盖该法下的主流解除/补偿等场景，避免路由彻底排除正确来源）
        if "劳动合同法" not in matched:
            matched = ["劳动合同法"] + matched
        return matched

    def strategy_C_query(query_text, k=p1.CANDIDATE_K):
        t0 = time.perf_counter()
        routed_laws = route_query(query_text)
        per_source_results = {}
        for src in routed_laws:
            if src not in sub_retrievers:
                continue
            evs = sub_retrievers[src].search_legal_knowledge(query_text, k=k)
            per_source_results[src] = [{"source": e.source, "article": e.article, "score": e.metadata.get("score")} for e in evs]
        merged = []
        maxlen = max((len(v) for v in per_source_results.values()), default=0)
        for i in range(maxlen):
            for src in routed_laws:
                lst = per_source_results.get(src, [])
                if i < len(lst):
                    merged.append(lst[i])
        elapsed = time.perf_counter() - t0
        return merged[:k], elapsed, routed_laws

    strategy_B_records = []
    strategy_C_records = []
    routing_log = []
    for r in label_rows:
        relevant_pairs, in_kb_pairs = [], []
        for item in r["_resolved"]:
            if item.get("unparseable") or item["article"] is None:
                continue
            pair = (item["law"], item["article"])
            relevant_pairs.append(pair)
            if item["article"] in kbs["kb44"]["by_article_sources"] and item["law"] in kbs["kb44"]["by_article_sources"][item["article"]]:
                in_kb_pairs.append(pair)

        candsB, elapsedB = strategy_B_query(r["query_text"])
        scoresB = p1.score_metrics(candsB, relevant_pairs, in_kb_pairs)
        strategy_B_records.append({"contract_id": r["contract_id"], "query_id": r["query_id"],
                                    "relevant_pairs": relevant_pairs, "scores_by_k": scoresB})

        candsC, elapsedC, routed = strategy_C_query(r["query_text"])
        scoresC = p1.score_metrics(candsC, relevant_pairs, in_kb_pairs)
        strategy_C_records.append({"contract_id": r["contract_id"], "query_id": r["query_id"],
                                    "relevant_pairs": relevant_pairs, "scores_by_k": scoresC})
        routing_log.append({"contract_id": r["contract_id"], "query_id": r["query_id"], "routed_laws": routed})

    agg_A = p1.aggregate(strategy_A_records)
    agg_B = p1.aggregate(strategy_B_records)
    agg_C = p1.aggregate(strategy_C_records)

    # 第26/35条专项命中率（三方案）
    def special_hit_rate(records_by_cid_qid, target_article, k=20):
        hits, total = 0, 0
        for r in wp_rows:
            rec = records_by_cid_qid.get((r["contract_id"], r["query_id"]))
            if rec is None:
                continue
            for p in rec["relevant_pairs"]:
                if p[1] == target_article:
                    total += 1
                    if p in rec["scores_by_k"][k]["hits"]:
                        hits += 1
        return hits, total

    recA = {(r["contract_id"], r["query_id"]): r for r in strategy_A_records}
    recB = {(r["contract_id"], r["query_id"]): r for r in strategy_B_records}
    recC = {(r["contract_id"], r["query_id"]): r for r in strategy_C_records}

    special = {}
    for name, rec in [("A", recA), ("B", recB), ("C", recC)]:
        h26, t26 = special_hit_rate(rec, "第二十六条")
        h35, t35 = special_hit_rate(rec, "第三十五条")
        special[name] = {"第二十六条": f"{h26}/{t26}", "第三十五条": f"{h35}/{t35}"}

    # 知识库外目标造成的未命中比例（口径A的miss中，有多少是因为target不在kb44）
    def oob_miss_ratio(records):
        total_miss, oob_miss = 0, 0
        for r in records:
            for p in r["relevant_pairs"]:
                if p not in r["scores_by_k"][20]["hits"]:
                    total_miss += 1
                    if p[0] not in kbs["kb44"]["by_article_sources"].get(p[1], []):
                        oob_miss += 1
        return oob_miss, total_miss

    oob_A = oob_miss_ratio(strategy_A_records)
    oob_B = oob_miss_ratio(strategy_B_records)
    oob_C = oob_miss_ratio(strategy_C_records)

    strategy_rows = []
    for name, agg, oob, timing in [
        ("A_global_bm25", agg_A, oob_A, None),
        ("B_per_source_index_roundrobin", agg_B, oob_B, None),
        ("C_query_routing", agg_C, oob_C, None),
    ]:
        strategy_rows.append({
            "strategy": name, "n": agg["n"],
            "recall@5": agg["recall@5_lensA"], "recall@10": agg["recall@10_lensA"], "recall@20": agg["recall@20_lensA"],
            "mrr@10": agg["mrr@10"], "ndcg@10": agg["ndcg@10"],
            "oob_miss_count": oob[0], "total_miss_count": oob[1],
            "oob_miss_ratio": (oob[0] / oob[1]) if oob[1] else None,
            "art26_hit": special[name.split("_")[0]]["第二十六条"],
            "art35_hit": special[name.split("_")[0]]["第三十五条"],
        })

    with open(OUT_DIR / "strategy_comparison.csv", "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = list(strategy_rows[0].keys())
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in strategy_rows:
            w.writerow(row)

    print(json.dumps(strategy_rows, ensure_ascii=False, indent=2))

    # 路由规则触发统计(方案C)，用于报告中说明路由分布，不涉及标签
    from collections import Counter
    route_dist = Counter(tuple(sorted(r["routed_laws"])) for r in routing_log)
    with open(OUT_DIR / "strategy_C_routing_distribution.json", "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in route_dist.items()}, f, ensure_ascii=False, indent=2)

    return {"wp_detail": wp_detail, "strategy_rows": strategy_rows, "route_dist": route_dist, "ctx": ctx}


if __name__ == "__main__":
    main()
