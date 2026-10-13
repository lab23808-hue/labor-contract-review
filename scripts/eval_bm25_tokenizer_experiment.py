"""BM25 中文分词策略控制变量实验：char_bigram vs jieba。

【这个脚本在测什么、为什么测】
    上一轮 Dense/BM25/RRF 对照实验里，BM25 用的是"字符 2-gram"分词
    （本机没装 jieba 时的退化方案）——人工检查过分词结果，发现数字/金额被
    切碎（"800元"→`币8`/`80`/`00`/`0元`）、标点会粘进 token（"致，"）。
    但 BM25 在那批数据上的指标反而全面优于 Dense，说明"分词粗糙"不等于
    "效果差"。本轮只做一件事：**装上 jieba，用完全一样的 BM25 参数和评估
    流程，换一种分词方式重新跑一遍，看真实指标会不会变好**——不预先假定
    jieba 一定更好，因为字符 2-gram 在"query 和知识库用同一套规则切分"
    这个前提下也能工作，jieba 切出的词边界不一定总是对检索有利（比如把
    "工作地点"切成"工作"+"地点"两个词，反而可能让"工作"这个高频词引入更多
    噪声匹配）。

【输入 / 输出】
    输入：
        - data/eval_samples/retrieval_eval_samples.json（不改）
        - data/knowledge/*.txt（通过 KnowledgeLoader 重新切分，不改切分逻辑）
    输出：
        - data/eval_samples/results/bm25_tokenizer_experiment_<时间戳>.json
        - data/eval_samples/results/bm25_tokenizer_experiment_<时间戳>.md

【candidate_k 和 final_top_k 的区别】
    和上一轮 Dense/BM25/RRF 实验完全一样的定义：candidate_k=20 是 BM25 每次
    检索内部取的候选深度；final_top_k∈{5,10,20} 是从这 20 个候选里截断、
    拿去算指标的数量。两个分词组用的 candidate_k/final_top_k 完全相同。

【固定不变 vs 唯一改变的变量】
    固定：query 原文、相关法条标签（标准答案）、知识库文本和切分结果、
         BM25 参数（k1=1.5, b=0.75）、candidate_k=20、final_top_k={5,10,20}、
         指标计算公式（Recall/MRR/nDCG 的实现直接从
         scripts/eval_retrieval_strategy_experiment.py 里 import 过来，
         不是重新写一套，保证两轮实验的数字可以直接比较）、两套评估口径
         （188 条原始样本 / 47 个独立场景）。
    唯一改变的变量：分词器——char_bigram（对照组，上一轮已经真实跑过、这里
    原样复用同一段实现，不做任何改动）vs jieba（本轮新增的对照组）。

【运行】
    先确认装了 jieba（没装会自动跳过 jieba 这组，只跑 char_bigram，并在
    报告里明确写"本次未能比较"，不会假装跑了）：
        pip install jieba==0.42.1
    然后：
        python scripts/eval_bm25_tokenizer_experiment.py
    依赖：只多了 jieba 这一个包（纯 Python，不需要编译），char_bigram 组
    不需要任何新依赖。

【分词实现细节】
    char_bigram：和 eval_retrieval_strategy_experiment.py::_get_tokenizer()
        里字符 2-gram 分支的实现逐字相同（直接复制过来，不是重新写、不是
        调用它——因为那个函数会按"是否装了 jieba"自动选择，这里需要能够
        无条件强制选 char_bigram 作对照组，所以单独复制一份，但保证逻辑
        完全不变：按字符切（跳过空白），相邻两个字符滑动组成一个 token）。
    jieba：`list(jieba.cut(text))`，过滤空白 token，不做额外的数字/金额/
        法条编号特殊处理——这是 jieba 默认分词模式下最朴素的用法，用来看
        "什么都不额外优化，只换分词器"这一个变量的真实效果。
        金额/法条编号/标点的处理方式会在脚本输出里给出具体分词结果样例，
        由人工检查，不在这里做任何预判断。

【安全】
    本脚本完全不涉及 Dense、不连接任何 Chroma（临时的或正式的），纯粹是对
    已经切分好的知识库文本（内存里的 Evidence 列表）跑两遍 BM25，不可能
    碰到正式数据库。不修改 generate_query()、rag/retriever.py、
    rag/database.py、规则机制，不调整 RRF（本轮不涉及 RRF），不做 query
    改写实验。
"""

import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

# 直接复用上一轮脚本里已经验证过的样本加载/场景分组/知识库切分/BM25实现/
# 评分公式——不重新写一套，保证两轮实验在"怎么算指标"这件事上完全一致，
# 可以直接比较数字。
strategy_mod = importlib.import_module("eval_retrieval_strategy_experiment")
_load_evaluable_samples = strategy_mod._load_evaluable_samples
_build_scenarios = strategy_mod._build_scenarios
_load_knowledge_evidences = strategy_mod._load_knowledge_evidences
_load_knowledge_documents_for_bm25 = strategy_mod._load_knowledge_documents_for_bm25
_BM25Index = strategy_mod._BM25Index
_score = strategy_mod._score
_aggregate = strategy_mod._aggregate
CANDIDATE_K = strategy_mod.CANDIDATE_K
FINAL_TOP_KS = strategy_mod.FINAL_TOP_KS

RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples" / "results"
BM25_K1 = 1.5
BM25_B = 0.75


# ======================================================================
# 两个分词器：char_bigram（对照组，原样复制）、jieba（本轮新增）
# ======================================================================

def _char_bigram_tokenizer(text: str) -> list[str]:
    """和 eval_retrieval_strategy_experiment.py::_get_tokenizer() 里的
    char_bigram 分支逐字相同，不做任何修改——作为本轮的对照组实现。
    输入：一段文本；输出：相邻两字符滑动组成的 token 列表（单字文本退化为
    单字列表），跳过空白字符。
    """
    chars = [c for c in text if not c.isspace()]
    if len(chars) <= 1:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def _try_build_jieba_tokenizer():
    """尝试 import jieba 并返回 (version, tokenize_fn)；没装则返回 (None, None)。
    tokenize_fn 输入一段文本，输出 jieba 默认模式分出的词列表（过滤空白 token）。
    """
    try:
        import jieba  # type: ignore
    except ImportError:
        return None, None

    version = getattr(jieba, "__version__", "unknown")

    def _tok(text: str) -> list[str]:
        return [t for t in jieba.cut(text) if t.strip()]

    return version, _tok


# ======================================================================
# 单个分词器跑完整 BM25 实验：建索引 + 47 个场景检索 + 两套口径指标
# ======================================================================

def _run_one_tokenizer(tokenizer_name: str, tokenize, scenarios: list[dict], bm25_docs: list[dict]) -> dict:
    """输入：分词器名字、分词函数、47 个场景、知识库文档列表。
    输出：{"index_build_seconds", "scenarios": [...], "aggregate_sample_level",
          "aggregate_scenario_level"} —— 和上一轮 Dense/BM25/RRF 实验的
    结果结构保持一致，方便对照着看。
    """
    t0 = time.perf_counter()
    index = _BM25Index(bm25_docs, tokenize)
    build_seconds = round(time.perf_counter() - t0, 3)

    scenario_records = []
    query_seconds = []
    for sc in scenarios:
        relevant_pairs = set(tuple(p) for p in sc["relevant_pairs"])
        t1 = time.perf_counter()
        candidates = index.search(sc["query"], CANDIDATE_K)
        query_seconds.append(time.perf_counter() - t1)
        retrieved_pairs = [(c["source"], c["article"]) for c in candidates]
        scenario_records.append(
            {
                "query": sc["query"],
                "relevant_pairs": sc["relevant_pairs"],
                "member_sample_ids": sc["member_sample_ids"],
                "occurrence_count": sc["occurrence_count"],
                "candidates": candidates,
                "scores_by_k": {str(k): _score(relevant_pairs, retrieved_pairs, k) for k in FINAL_TOP_KS},
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

    return {
        "tokenizer": tokenizer_name,
        "index_build_seconds": build_seconds,
        "distinct_query_count": len(query_seconds),
        "total_query_seconds": round(sum(query_seconds), 3),
        "mean_query_seconds": round(sum(query_seconds) / len(query_seconds), 4) if query_seconds else None,
        "aggregate_sample_level": aggregate_sample_level,
        "aggregate_scenario_level": aggregate_scenario_level,
        "scenarios": scenario_records,
    }


# ======================================================================
# 主流程
# ======================================================================

def run() -> dict:
    evaluable = _load_evaluable_samples()
    scenarios = _build_scenarios(evaluable)
    knowledge_evidences = _load_knowledge_evidences()
    bm25_docs = _load_knowledge_documents_for_bm25(knowledge_evidences)
    print(f"样本数={len(evaluable)}  独立场景数={len(scenarios)}  知识库文档数={len(bm25_docs)}")
    print(f"BM25 参数: k1={BM25_K1}, b={BM25_B}（两组分词都用这同一套参数，不调）")

    print("\n运行 char_bigram 组（对照组）...")
    char_bigram_result = _run_one_tokenizer("char_bigram", _char_bigram_tokenizer, scenarios, bm25_docs)

    jieba_version, jieba_tokenize = _try_build_jieba_tokenizer()
    if jieba_tokenize is None:
        print("jieba 未安装，本次跳过 jieba 组——只有 char_bigram 的真实结果，不会用假数据填充 jieba 组。")
        print("如需比较，请先运行: pip install jieba==0.42.1，然后重新执行本脚本。")
        jieba_result = None
    else:
        print(f"\n检测到 jieba（版本 {jieba_version}），运行 jieba 组...")
        jieba_result = _run_one_tokenizer("jieba", jieba_tokenize, scenarios, bm25_docs)

    # ---- 重点样本核查：社保补偿条款 / 工作地点场景 ----
    def _find_scenario(predicate):
        for r in [char_bigram_result, jieba_result]:
            if r is None:
                continue
            for sc in r["scenarios"]:
                if predicate(sc["query"]):
                    yield r["tokenizer"], sc
                    break

    social_insurance_ranks = {}
    workplace_ranks = {}
    for tok_name, sc in _find_scenario(lambda q: "自愿放弃" in q and "800" in q):
        rel = [tuple(p) for p in sc["relevant_pairs"]]
        ranks = {}
        for i, c in enumerate(sc["candidates"]):
            key = (c["source"], c["article"])
            if key in rel:
                ranks[f"{key[0]}{key[1]}"] = i + 1
        social_insurance_ranks[tok_name] = ranks
    for tok_name, sc in _find_scenario(lambda q: q.startswith("工作地点")):
        rel = [tuple(p) for p in sc["relevant_pairs"]]
        ranks = {}
        for i, c in enumerate(sc["candidates"]):
            key = (c["source"], c["article"])
            if key in rel:
                ranks[f"{key[0]}{key[1]}"] = i + 1
        workplace_ranks[tok_name] = ranks

    # ---- char_bigram vs jieba：谁找回了谁漏掉的法条 ----
    comparison = None
    if jieba_result is not None:
        char_only, jieba_only, both, neither = [], [], [], []
        cb_by_key = {(sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc for sc in char_bigram_result["scenarios"]}
        jb_by_key = {(sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc for sc in jieba_result["scenarios"]}
        for key in cb_by_key:
            rel = set(key[1])
            cb_hits = set((c["source"], c["article"]) for c in cb_by_key[key]["candidates"]) & rel
            jb_hits = set((c["source"], c["article"]) for c in jb_by_key[key]["candidates"]) & rel
            for art in rel:
                in_cb, in_jb = art in cb_hits, art in jb_hits
                entry = {"query": key[0][:30], "article": list(art)}
                if in_cb and not in_jb:
                    char_only.append(entry)
                elif in_jb and not in_cb:
                    jieba_only.append(entry)
                elif in_cb and in_jb:
                    both.append(entry)
                else:
                    neither.append(entry)
        comparison = {
            "char_bigram_found_jieba_missed": char_only,
            "jieba_found_char_bigram_missed": jieba_only,
            "both_found_count": len(both),
            "neither_found": neither,
        }

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "bm25_k1": BM25_K1,
        "bm25_b": BM25_B,
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "total_evaluable_samples": len(evaluable),
        "distinct_scenario_count": len(scenarios),
        "jieba_available": jieba_tokenize is not None,
        "jieba_version": jieba_version,
        "char_bigram_result": char_bigram_result,
        "jieba_result": jieba_result,
        "social_insurance_clause_ranks": social_insurance_ranks,
        "workplace_clause_ranks": workplace_ranks,
        "char_bigram_vs_jieba_comparison": comparison,
    }
    return result


def _print_summary(result: dict) -> None:
    print("=" * 78)
    print(f"candidate_k={result['candidate_k']}  final_top_k={result['final_top_k_values']}  bm25(k1={result['bm25_k1']}, b={result['bm25_b']})")
    print(f"样本数={result['total_evaluable_samples']}  独立场景数={result['distinct_scenario_count']}")
    print(f"jieba_available={result['jieba_available']}  jieba_version={result['jieba_version']}")
    for name, res in [("char_bigram", result["char_bigram_result"]), ("jieba", result["jieba_result"])]:
        if res is None:
            print(f"\n--- {name}：本次未运行 ---")
            continue
        print(f"\n--- {name} ---")
        for basis_name, basis in [("原始样本口径(188)", res["aggregate_sample_level"]), ("独立场景口径(47)", res["aggregate_scenario_level"])]:
            print(f"  {basis_name}:")
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                print(f"    K={k:>2}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}")
    print(f"\n社保补偿条款排名: {result['social_insurance_clause_ranks']}")
    print(f"工作地点条款排名: {result['workplace_clause_ranks']}")
    if result["char_bigram_vs_jieba_comparison"]:
        c = result["char_bigram_vs_jieba_comparison"]
        print(f"\nchar_bigram 找到但 jieba 没找到: {len(c['char_bigram_found_jieba_missed'])} 个")
        print(f"jieba 找到但 char_bigram 没找到: {len(c['jieba_found_char_bigram_missed'])} 个")
        print(f"两者都没找到: {len(c['neither_found'])} 个")


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = ["# BM25 中文分词策略对照实验：char_bigram vs jieba\n\n"]
    lines.append(f"运行时间（UTC）：{result['run_at']}\n\n")
    lines.append(
        f"BM25 参数：k1={result['bm25_k1']}, b={result['bm25_b']}；"
        f"candidate_k={result['candidate_k']}；final_top_k={result['final_top_k_values']}；"
        f"样本数={result['total_evaluable_samples']}；独立场景数={result['distinct_scenario_count']}\n\n"
    )
    lines.append(f"jieba 是否可用：{result['jieba_available']}（版本：{result['jieba_version']}）\n\n")

    if result["jieba_result"] is None:
        lines.append("**本次只跑了 char_bigram 对照组，jieba 未安装，没有可比较的 jieba 结果。**\n\n")

    lines.append("## 指标对照\n\n")
    lines.append("| 分词器 | 口径 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|---|\n")
    for name, res in [("char_bigram", result["char_bigram_result"]), ("jieba", result["jieba_result"])]:
        if res is None:
            continue
        for basis_name, basis in [("原始样本(188)", res["aggregate_sample_level"]), ("独立场景(47)", res["aggregate_scenario_level"])]:
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                lines.append(f"| {name} | {basis_name} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")

    lines.append("\n## 重点样本\n\n")
    lines.append(f"社保补偿条款（第二十六条/第十七条）排名：`{result['social_insurance_clause_ranks']}`\n\n")
    lines.append(f"工作地点场景（第二十六条）排名：`{result['workplace_clause_ranks']}`\n\n")

    if result["char_bigram_vs_jieba_comparison"]:
        c = result["char_bigram_vs_jieba_comparison"]
        lines.append("## char_bigram vs jieba 差异\n\n")
        lines.append(f"- char_bigram 找到但 jieba 没找到：{c['char_bigram_found_jieba_missed']}\n")
        lines.append(f"- jieba 找到但 char_bigram 没找到：{c['jieba_found_char_bigram_missed']}\n")
        lines.append(f"- 两者都没找到：{c['neither_found']}\n")

    lines.append(
        "\n## 结论与限制\n\n详见对话中的文字分析（哪种分词器更好、差异来自哪些场景、是否值得采用、"
        "结论的限制）。本报告只保留可复现的真实数字。\n"
    )
    output_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    result = run()
    _print_summary(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"bm25_tokenizer_experiment_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")

    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print(f"简短报告已写出: {md_path}")


if __name__ == "__main__":
    main()
