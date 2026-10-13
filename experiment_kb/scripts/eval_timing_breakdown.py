#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_timing_breakdown.py —— 补测脚本：拆分 Dense(embedding-only / 向量检索-only)
和 BM25(分词-only / 排名-only) 的细粒度耗时。

【为什么需要这个脚本】
已有的 working_kb_retrieval_experiment_*.json / baseline_kb_retrieval_experiment_*.json
里，Dense 记的是"embedding+向量检索"合并耗时(dense_query_embedding_and_retrieval)，
BM25 记的是"分词+排名"合并耗时(bm25_tokenization_and_ranking)。用户要求进一步
拆分成"Query Embedding 耗时"vs"向量检索耗时"、"分词耗时"vs"BM25排名耗时"两段，
这两段在已有结果文件里不存在，必须新增一次独立的计时测试才能拿到——
不是重新跑一次完整质量实验，只补测缺失的耗时拆分，不重新调用整套评分逻辑，
不修改任何质量指标(Recall/MRR/nDCG继续使用已有结果文件，不在这里重算)。

【复用已有代码，不重新实现】
本脚本直接 import 同目录下的 eval_working_kb_retrieval.py（下称"主脚本"），
复用它的：
  - _load_working_knowledge_evidences() / _load_evaluable_samples() / _build_scenarios()
  - _get_tokenizer() / _load_knowledge_documents_for_bm25() / _BM25Index
  - _assert_isolated_from_official_db() / _assert_no_arbitration_leak()
  - _verify_working_snapshot_unchanged()
  - WORKING_DIR / WORKING_KNOWLEDGE_DIR / WORKING_SAMPLES_PATH /
    RECORDED_WORKING_SNAPSHOT_PATH / KB_SOURCE_LABEL 这几个模块全局变量
    （--kb-source baseline 时用和主脚本完全相同的方式重新指向 baseline/）
本脚本新增的代码只有："怎么把 Dense/BM25 各自拆成两段计时"，没有重新实现
知识库加载、BM25 排名算法、Dense 检索调用本身。

【Dense 拆分的实现方式——为什么要绕过 ChromaKnowledgeBase.similarity_search()】
rag/database.py 的 similarity_search(query, k) 内部是
self._store.similarity_search_with_score(query, k=k) 一次调用完成"embedding+
向量检索"，没有公开的"只 embedding 不检索"或"只检索不 embedding"接口。
要拆分成两段又不重复计算 embedding（重复计算会让"向量检索"这一段的计时虚高，
把一次额外的 embedding 耗时算进去），本脚本：
  1) 单独调用 embedder.embed_query(query) 计时，得到 embedding_only_seconds；
  2) 用这个已经算好的向量，直接调用 kb._store._collection.query(
       query_embeddings=[embedding], n_results=k, include=["distances","metadatas"])
     计时，得到 vector_search_only_seconds —— 这是标准 chromadb Collection 的
     公开方法（不是内部私有逻辑），和主脚本里 count()/delete() 已经在用的
     "通过 kb._store._collection 访问底层 chromadb Collection 对象"是同一种
     访问方式，不是本脚本新发明的黑客手法。
  3) metadata 里的 "source"/"article" 字段名和写入时（rag/knowledge_loader.py
     的 _to_metadata()）完全一致，所以可以直接从 collection.query() 返回的
     metadatas 里读出来，不需要重新实现 Evidence 对象的构造。

【BM25 拆分的实现方式】
_BM25Index.search(query, k) 内部是 self.tokenize(query) 再做 BM25 打分排序，
没有暴露"只分词"或"只打分"的接口。本脚本直接调用同一个 bm25_index 实例的
tokenize 函数做分词计时，再把分词结果喂给一段和 _BM25Index.search() 内部
打分循环逐行一致的打分代码（不改算法，只是把"分词"这一行单独计时、"打分+
排序"这几行单独计时），避免重新实现 BM25Okapi 公式本身。
当前 char_bigram_baseline 的实现里，"Query规范化"和"分词"是同一步（过滤空白
后直接两两配对，没有单独的规范化子步骤），所以本脚本只能给出"分词(含规范化)"
一段 + "排名"一段，凡是文档里要求的"Query规范化"单独计时，如实标注
NOT_MEASURED_NO_SEPARATE_STEP_IN_CODE（代码里没有这一步，不是漏测）。

【公平性】
- 固定使用 char_bigram 分词器（本轮技术决策锁定的主候选），不跑 jieba。
- 和主脚本一样，运行前校验 experiment_kb/{working,baseline}/ 的内容指纹没有
  被改动（复用 _verify_working_snapshot_unchanged()），不一致直接中止。
- 和主脚本一样，Dense 用隔离的临时 Chroma（落在 experiment_kb/tmp_runtime/
  内部），绝不触碰官方 data/chroma。
- 每个 Query 先做一次"预热"调用（不计入统计），避免把模型/索引冷启动的开销
  混进"稳定态单次查询"的计时里；预热耗时单独记录，不混入 P50/P95。
- 本脚本默认重复 3 次完整扫描 47 个 Query（可用 --repeats 调整），这样
  P50/P95 既反映"47个不同Query的单次延迟分布"，也能额外给出"同一个Query
  重复3次"的稳定性参考（repeat_variance_seconds 字段），两种统计分开标注，
  不混为一谈。

【产出】
experiment_kb/results/timing_breakdown_{kb_source}_{timestamp}.json
——新文件，不覆盖任何历史结果。

【运行方式】
    python experiment_kb/scripts/eval_timing_breakdown.py --kb-source working
    python experiment_kb/scripts/eval_timing_breakdown.py --kb-source baseline

需要真实 BGE-M3 模型权重和网络（和主脚本一样），在用户本机已配置好的 venv 里运行。
本次任务按用户指令不在云端沙箱里尝试运行（沙箱无法安装 chromadb/BGE-M3 依赖，
此前已反复确认），结果待用户在本机运行后把真实输出回贴。
"""
import argparse
import json
import math
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
SCRIPTS_DIR = SCRIPT_PATH.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import eval_working_kb_retrieval as base  # noqa: E402  — 复用主脚本，不重新实现


def _timed_dense_breakdown(scenarios, knowledge_evidences, repeats: int):
    """返回 (dense_breakdown_perf_dict)。隔离临时 Chroma，用后删除。"""
    from rag import ChromaKnowledgeBase, KnowledgeLoader, build_embedder

    base.TMP_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    persist_dir = base.TMP_RUNTIME_DIR / f"timing_dense_{ts}"
    collection_name = f"experiment_kb_timing_dense_{ts}"
    base._assert_isolated_from_official_db(persist_dir, collection_name)

    try:
        t0 = time.perf_counter()
        embedder = build_embedder()
        cold_start_seconds = round(time.perf_counter() - t0, 3)

        t1 = time.perf_counter()
        kb = ChromaKnowledgeBase(embedder, persist_directory=persist_dir, collection_name=collection_name)
        loader = KnowledgeLoader(kb)
        loader.index(knowledge_evidences)
        build_seconds = round(time.perf_counter() - t1, 3)

        # 预热一次（不计入任何统计），避免把模型/索引的首次调用开销混进来
        if scenarios:
            warm_q = scenarios[0]["query"]
            _ = embedder.embed_query(warm_q)
            warm_emb = embedder.embed_query(warm_q)
            kb._store._collection.query(query_embeddings=[warm_emb], n_results=base.CANDIDATE_K, include=["distances", "metadatas"])

        embedding_only_seconds: list[float] = []
        search_only_seconds: list[float] = []
        combined_seconds: list[float] = []
        per_query_repeat_samples: dict[str, list[float]] = {}

        for rep in range(repeats):
            for sc in scenarios:
                q = sc["query"]
                t_emb = time.perf_counter()
                emb = embedder.embed_query(q)
                emb_elapsed = time.perf_counter() - t_emb

                t_search = time.perf_counter()
                kb._store._collection.query(
                    query_embeddings=[emb], n_results=base.CANDIDATE_K, include=["distances", "metadatas"]
                )
                search_elapsed = time.perf_counter() - t_search

                embedding_only_seconds.append(emb_elapsed)
                search_only_seconds.append(search_elapsed)
                combined_seconds.append(emb_elapsed + search_elapsed)
                per_query_repeat_samples.setdefault(q, []).append(emb_elapsed + search_elapsed)

        def _stats(arr):
            if not arr:
                return {"n": 0}
            return {
                "n": len(arr),
                "total_seconds": round(sum(arr), 4),
                "mean_seconds": round(statistics.mean(arr), 5),
                "p50_seconds": round(statistics.median(arr), 5),
                "p95_seconds": round(statistics.quantiles(arr, n=100)[94], 5) if len(arr) > 1 else None,
            }

        # 同一 Query 重复 repeats 次的稳定性方差（和"不同Query单次分布"的P50/P95明确分开）
        repeat_stability = {}
        if repeats > 1:
            for q, samples in per_query_repeat_samples.items():
                if len(samples) > 1:
                    repeat_stability[q[:40]] = {
                        "n_repeats": len(samples),
                        "stdev_seconds": round(statistics.stdev(samples), 5),
                        "mean_seconds": round(statistics.mean(samples), 5),
                    }

        return {
            "cold_start_and_model_init": {"embedder_load_seconds": cold_start_seconds},
            "index_build_seconds": build_seconds,
            "warmup_note": "每轮重复前先对第一个Query做2次预热调用(embed_query+collection.query)，不计入下面任何统计量",
            "repeats_of_full_47_query_scan": repeats,
            "embedding_only": _stats(embedding_only_seconds),
            "vector_search_only": _stats(search_only_seconds),
            "combined_embedding_plus_search": _stats(combined_seconds),
            "same_query_repeat_stability": (
                repeat_stability if repeats > 1 else
                "NOT_MEASURED(repeats=1，未重复同一Query，无法计算同Query稳定性方差，只有不同Query的单次分布)"
            ),
            "measurement_boundary_note": (
                "embedding_only 只计时 embedder.embed_query(query)；vector_search_only 只计时 "
                "kb._store._collection.query(query_embeddings=[已算好的向量], n_results=candidate_k)，"
                "没有重复计算embedding，避免把一次额外embedding耗时错算进向量检索里。"
                "combined_embedding_plus_search = 两段直接相加，用于和旧结果文件里的"
                "dense_query_embedding_and_retrieval做对照(旧字段是similarity_search_with_score"
                "一次调用内部自动完成embedding+检索，口径应一致，但本脚本是两次独立调用相加，"
                "如果两者数字有系统性差异，可能来自两次调用之间的调度开销，未进一步拆解，如实标注)。"
            ),
        }
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)


def _timed_bm25_breakdown(scenarios, knowledge_evidences, repeats: int):
    bm25_docs = base._load_knowledge_documents_for_bm25(knowledge_evidences)
    tokenizer_name, tokenize = base._get_tokenizer(force="char_bigram")
    assert tokenizer_name.startswith("char_bigram"), f"本补测脚本按锁定决策只用char_bigram，实际={tokenizer_name}"

    bm25_index = base._BM25Index(bm25_docs, tokenize)

    # 预热一次
    if scenarios:
        _ = tokenize(scenarios[0]["query"])

    tokenize_only_seconds: list[float] = []
    rank_only_seconds: list[float] = []

    def _rank_given_tokens(q_tokens, k):
        # 与 _BM25Index.search() 内部打分循环逐行一致，只是把"分词"抽出去单独计时，
        # 不改变 BM25Okapi 打分公式本身（k1=1.5, b=0.75）。
        scores = [0.0] * bm25_index.N
        for i in range(bm25_index.N):
            tf = bm25_index.doc_tf[i]
            dl = bm25_index.doc_lens[i]
            denom_norm = bm25_index.k1 * (1 - bm25_index.b + bm25_index.b * (dl / bm25_index.avgdl if bm25_index.avgdl else 0))
            score = 0.0
            for t in q_tokens:
                if t not in tf:
                    continue
                idf = bm25_index.idf.get(t, 0.0)
                freq = tf[t]
                score += idf * (freq * (bm25_index.k1 + 1)) / (freq + denom_norm)
            scores[i] = score
        order = sorted(range(bm25_index.N), key=lambda i: (-scores[i], i))
        return order[:k]

    for rep in range(repeats):
        for sc in scenarios:
            q = sc["query"]
            t_tok = time.perf_counter()
            q_tokens = tokenize(q)
            tok_elapsed = time.perf_counter() - t_tok

            t_rank = time.perf_counter()
            _rank_given_tokens(q_tokens, base.CANDIDATE_K)
            rank_elapsed = time.perf_counter() - t_rank

            tokenize_only_seconds.append(tok_elapsed)
            rank_only_seconds.append(rank_elapsed)

    def _stats(arr):
        if not arr:
            return {"n": 0}
        return {
            "n": len(arr), "total_seconds": round(sum(arr), 4),
            "mean_seconds": round(statistics.mean(arr), 6),
            "p50_seconds": round(statistics.median(arr), 6),
            "p95_seconds": round(statistics.quantiles(arr, n=100)[94], 6) if len(arr) > 1 else None,
        }

    return {
        "tokenizer_used": tokenizer_name,
        "index_build_seconds_for_this_breakdown_run": "见主实验结果文件的index_build_update_delete.bm25.initial_build_seconds，本脚本不重复测量构建耗时",
        "repeats_of_full_47_query_scan": repeats,
        "query_normalization_note": "NOT_MEASURED_NO_SEPARATE_STEP_IN_CODE(char_bigram_baseline实现里过滤空白后直接两两配对，规范化和分词是同一步，代码里没有可单独计时的规范化子步骤)",
        "tokenize_only": _stats(tokenize_only_seconds),
        "bm25_rank_only": _stats(rank_only_seconds),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-source", choices=["working", "baseline"], default="working")
    parser.add_argument("--repeats", type=int, default=3, help="完整扫描47个Query的重复次数，用于同Query稳定性方差(默认3)")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    if args.kb_source == "baseline":
        base.WORKING_DIR = base.EXPERIMENT_DIR / "baseline"
        base.WORKING_KNOWLEDGE_DIR = base.WORKING_DIR / "data" / "knowledge"
        base.WORKING_SAMPLES_PATH = base.WORKING_DIR / "data" / "eval_samples" / "retrieval_eval_samples.json"
        base.RECORDED_WORKING_SNAPSHOT_PATH = base.EXPERIMENT_DIR / "snapshots" / "baseline_snapshot.json"
        base.KB_SOURCE_LABEL = "baseline"

    base._assert_no_arbitration_leak()
    snapshot_before = base._verify_working_snapshot_unchanged("before_run")
    if snapshot_before.get("checked") and snapshot_before.get("changed"):
        raise SystemExit(f"{args.kb_source} 知识库内容指纹和记录不一致，已中止，未做任何计时测试：{snapshot_before['diff']}")

    evaluable = base._load_evaluable_samples()
    scenarios = base._build_scenarios(evaluable)
    knowledge_evidences = base._load_working_knowledge_evidences()

    print(f"[1/2] Dense embedding-only / 向量检索-only 拆分计时（{args.kb_source}，{len(scenarios)}个场景 x {args.repeats}次）...")
    dense_breakdown = _timed_dense_breakdown(scenarios, knowledge_evidences, args.repeats)

    print(f"[2/2] BM25(char_bigram) 分词-only / 排名-only 拆分计时...")
    bm25_breakdown = _timed_bm25_breakdown(scenarios, knowledge_evidences, args.repeats)

    snapshot_after = base._verify_working_snapshot_unchanged("after_run")

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "补测Dense embedding-only/向量检索-only、BM25分词-only/排名-only的细粒度耗时拆分，不重新计算质量指标(Recall/MRR/nDCG继续以已有结果文件为准)",
        "kb_source_label": args.kb_source,
        "knowledge_evidence_count": len(knowledge_evidences),
        "scenario_count": len(scenarios),
        "candidate_k": base.CANDIDATE_K,
        "snapshot_check": {"before_run": snapshot_before, "after_run": snapshot_after},
        "dense_timing_breakdown": dense_breakdown,
        "bm25_timing_breakdown": bm25_breakdown,
        "caveat": "本文件只补测耗时，不包含Recall/MRR/nDCG；对应的质量指标见同目录下"
                  f"{args.kb_source}_kb_retrieval_experiment_*.json。并行端到端耗时本脚本仍未测量"
                  "（Dense/BM25本来就是两个独立通道，本脚本串行测两个通道各自的细分耗时，"
                  "不构成真正的并发测量，不得当作并行耗时使用）。",
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else base.RESULTS_DIR / f"timing_breakdown_{args.kb_source}_{ts}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入：{out_path}")
    print("Dense embedding_only P50/P95:", dense_breakdown["embedding_only"].get("p50_seconds"), "/", dense_breakdown["embedding_only"].get("p95_seconds"))
    print("Dense vector_search_only P50/P95:", dense_breakdown["vector_search_only"].get("p50_seconds"), "/", dense_breakdown["vector_search_only"].get("p95_seconds"))
    print("BM25 tokenize_only P50/P95:", bm25_breakdown["tokenize_only"].get("p50_seconds"), "/", bm25_breakdown["tokenize_only"].get("p95_seconds"))
    print("BM25 rank_only P50/P95:", bm25_breakdown["bm25_rank_only"].get("p50_seconds"), "/", bm25_breakdown["bm25_rank_only"].get("p95_seconds"))


if __name__ == "__main__":
    main()
