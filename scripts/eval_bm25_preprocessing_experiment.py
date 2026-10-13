"""BM25 文本预处理控制变量实验：char_bigram_baseline vs char_bigram_clean。

【这个脚本在测什么、为什么测】
    先检查了现有 char_bigram 分词的实现（eval_bm25_tokenizer_experiment.py::
    _char_bigram_tokenizer，本脚本直接 import 过来，不重写）：

        chars = [c for c in text if not c.isspace()]
        return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]

    核查结论（真实代码检查，不是猜测）：
        - 空白字符（空格、换行 \\n、全角空格 \\u3000 等，Python 的
          `str.isspace()` 能判断的都算）**本身不会单独成为 token**，上面这
          一行已经把它们过滤掉了。但过滤之后，原来被空白隔开的两个字符会
          被当成"相邻"字符配成一个 bigram——例如"工作地点\\n乙方"去掉换行后
          变成"工作地点乙方"，会产生"点乙"这个跨行拼接出来的伪 token，这是
          一个真实存在、此前没有专门处理过的边界效应。
        - 标点符号（，。；、《》等）**没有被过滤，会真实进入 token 统计**——
          之前人工检查分词样例时见过的"致，""险，""，乙"这些带标点的 token
          就是证据：标点被原样留在字符序列里，和前后字符一起组成了 bigram。

    本轮只验证一件事：在 char_bigram 分词**之前**加一道文本清洗（统一换行、
    去掉无意义空白、去掉标点符号），分词算法本身完全不变，能不能真的改善
    检索指标——不预先认定"清洗过的输入肯定更好"，清洗引入的"跨词边界重新
    拼接"也可能带来新的噪声，所以要用真实指标说话。

【输入 / 输出】
    输入：data/eval_samples/retrieval_eval_samples.json（不改）、
         data/knowledge/*.txt（通过 KnowledgeLoader 重新切分，不改切分逻辑）。
    输出：data/eval_samples/results/bm25_preprocessing_experiment_<时间戳>.json
         和同名 .md。

【两个版本】
    1. char_bigram_baseline：完全复用 _char_bigram_tokenizer，不加任何清洗，
       和上一轮 BM25 分词实验里的 char_bigram 组逐字相同（直接 import 这个
       函数，不是重新写一份"看起来一样"的实现）。
    2. char_bigram_clean：在送进 _char_bigram_tokenizer 之前，先用
       `_clean_text()` 做三件事（只做这三件，不做别的）：
           a) 统一换行——把 \\r\\n、\\r 都换成 \\n，避免同一份文本因为换行符
              写法不同而被切出不同的字符序列；
           b) 折叠连续空白——多个空格/换行压成一个，减少"同样的空白、因为
              重复次数不同而占据不同字符位置"的偶然影响；
           c) 去掉标点符号——用 Unicode 类别判断（`unicodedata.category(ch)
              .startswith("P")`，覆盖所有标点大类：连接号、短横线、开括号、
              闭括号、首尾引号、其他标点），不是手工列举几个标点符号，规则
              明确、可复现。**只删标点和空白，不删汉字、数字、字母，不改变
              数字本身的切分方式**（"800元"清洗前后都还是同样的字符序列
              交给同一个 bigram 函数，不会被这个脚本动过）。
       两个版本处理完之后都调用**同一个**未改动的 `_char_bigram_tokenizer`。

【固定不变 vs 唯一改变的变量】
    固定：query 原文、relevant 标签、知识库文本和切分结果、BM25 参数
         （k1=1.5, b=0.75，直接从 eval_retrieval_strategy_experiment.py
         import 过来）、candidate_k=20、final_top_k={5,10,20}、评分公式
         （Recall/MRR/nDCG，同样是 import 过来的，不重写）、两套评估口径
         （188 条原始样本 / 47 个独立场景）。
    唯一改变的变量：喂给 char_bigram 分词器之前的文本预处理方式。

【运行】
    python scripts/eval_bm25_preprocessing_experiment.py
    不需要额外依赖（`unicodedata` 是标准库）。

【安全】
    不连接任何 Chroma（临时的或正式的），纯粹是对内存里切分好的知识库文本
    （Evidence 列表）跑两遍 BM25。不修改 generate_query()、
    rag/retriever.py、rag/database.py、规则机制，不改变 BM25 参数本身，
    不改变数字处理逻辑，不删除任何法律文本内容（标点/空白清理不影响条文的
    实际汉字/数字内容）。输出文件带独立时间戳，不覆盖已有结果。
"""

import importlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

# 直接复用已经验证过的样本加载/场景分组/知识库切分/BM25实现/评分公式/
# 单分词器完整跑一遍的流程函数，以及 char_bigram 的原始实现本身——
# 不重新写，保证这轮和前两轮在"怎么算指标""baseline 分词器是什么"这两件
# 事上完全一致，数字可以直接比较。
strategy_mod = importlib.import_module("eval_retrieval_strategy_experiment")
tokenizer_mod = importlib.import_module("eval_bm25_tokenizer_experiment")

_load_evaluable_samples = strategy_mod._load_evaluable_samples
_build_scenarios = strategy_mod._build_scenarios
_load_knowledge_evidences = strategy_mod._load_knowledge_evidences
_load_knowledge_documents_for_bm25 = strategy_mod._load_knowledge_documents_for_bm25
CANDIDATE_K = strategy_mod.CANDIDATE_K
FINAL_TOP_KS = strategy_mod.FINAL_TOP_KS
BM25_K1 = tokenizer_mod.BM25_K1
BM25_B = tokenizer_mod.BM25_B
_char_bigram_tokenizer = tokenizer_mod._char_bigram_tokenizer  # 原始实现，不改一个字
_run_one_tokenizer = tokenizer_mod._run_one_tokenizer  # 建索引+47场景检索+两套口径指标，直接复用

RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples" / "results"

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _clean_text(text: str) -> str:
    """三步文本清洗，顺序固定、规则明确、可复现：
    1. 统一换行：\\r\\n、\\r 都换成 \\n。
    2. 折叠连续空白：一个或多个空白字符（含刚统一过的换行）压成一个空格。
    3. 去掉标点：按 Unicode 类别删除所有标点大类字符（P 开头的类别：
       Pc/Pd/Ps/Pe/Pi/Pf/Po），不手工列举字符表。
    不删除、不改写任何汉字、数字、字母——只影响标点和空白这两类字符。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("P"))
    return text


def _char_bigram_clean_tokenizer(text: str) -> list[str]:
    """clean 版本：先 `_clean_text()` 清洗，再交给未改动的
    `_char_bigram_tokenizer`。分词算法本身没有任何变化。
    """
    return _char_bigram_tokenizer(_clean_text(text))


# ======================================================================
# 主流程
# ======================================================================

def run() -> dict:
    evaluable = _load_evaluable_samples()
    scenarios = _build_scenarios(evaluable)
    knowledge_evidences = _load_knowledge_evidences()
    bm25_docs = _load_knowledge_documents_for_bm25(knowledge_evidences)
    print(f"样本数={len(evaluable)}  独立场景数={len(scenarios)}  知识库文档数={len(bm25_docs)}")
    print(f"BM25 参数: k1={BM25_K1}, b={BM25_B}（两组共用，不调）  candidate_k={CANDIDATE_K}")

    print("\n运行 char_bigram_baseline（原样复用，不加任何清洗）...")
    baseline_result = _run_one_tokenizer("char_bigram_baseline", _char_bigram_tokenizer, scenarios, bm25_docs)

    print("运行 char_bigram_clean（统一换行 + 折叠空白 + 去标点，之后用同一个分词函数）...")
    clean_result = _run_one_tokenizer("char_bigram_clean", _char_bigram_clean_tokenizer, scenarios, bm25_docs)

    # ---- 重点场景：社保补偿 / 工作地点 / 延迟支付（劳动报酬）----
    def _scenario_ranks(predicate) -> dict:
        out = {}
        for name, res in [("char_bigram_baseline", baseline_result), ("char_bigram_clean", clean_result)]:
            for sc in res["scenarios"]:
                if predicate(sc["query"]):
                    rel = [tuple(p) for p in sc["relevant_pairs"]]
                    ranks = {}
                    for i, c in enumerate(sc["candidates"]):
                        key = (c["source"], c["article"])
                        if key in rel:
                            ranks[f"{key[0]}{key[1]}"] = i + 1
                    out[name] = ranks
                    break
        return out

    social_insurance_ranks = _scenario_ranks(lambda q: "自愿放弃" in q and "800" in q)
    workplace_ranks = _scenario_ranks(lambda q: q.startswith("工作地点"))
    delayed_payment_ranks = _scenario_ranks(lambda q: q.startswith("劳动报酬") and "延迟支付" in q)

    # ---- baseline vs clean：谁找回了谁漏掉的法条 ----
    base_by_key = {(sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc for sc in baseline_result["scenarios"]}
    clean_by_key = {(sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc for sc in clean_result["scenarios"]}
    baseline_only, clean_only, both, neither = [], [], [], []
    for key in base_by_key:
        rel = set(key[1])
        base_hits = set((c["source"], c["article"]) for c in base_by_key[key]["candidates"]) & rel
        clean_hits = set((c["source"], c["article"]) for c in clean_by_key[key]["candidates"]) & rel
        for art in rel:
            in_base, in_clean = art in base_hits, art in clean_hits
            entry = {"query": key[0][:30], "article": list(art)}
            if in_base and not in_clean:
                baseline_only.append(entry)
            elif in_clean and not in_base:
                clean_only.append(entry)
            elif in_base and in_clean:
                both.append(entry)
            else:
                neither.append(entry)

    comparison = {
        "baseline_found_clean_missed": baseline_only,
        "clean_found_baseline_missed": clean_only,
        "both_found_count": len(both),
        "neither_found": neither,
    }

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "bm25_preprocessing_experiment",
        "versions_compared": ["char_bigram_baseline", "char_bigram_clean"],
        "bm25_k1": BM25_K1,
        "bm25_b": BM25_B,
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "total_evaluable_samples": len(evaluable),
        "distinct_scenario_count": len(scenarios),
        "baseline_result": baseline_result,
        "clean_result": clean_result,
        "social_insurance_clause_ranks": social_insurance_ranks,
        "workplace_clause_ranks": workplace_ranks,
        "delayed_payment_clause_ranks": delayed_payment_ranks,
        "baseline_vs_clean_comparison": comparison,
    }
    return result


def _print_summary(result: dict) -> None:
    print("=" * 78)
    print(f"candidate_k={result['candidate_k']}  final_top_k={result['final_top_k_values']}  bm25(k1={result['bm25_k1']}, b={result['bm25_b']})")
    print(f"样本数={result['total_evaluable_samples']}  独立场景数={result['distinct_scenario_count']}")
    for name, res in [("char_bigram_baseline", result["baseline_result"]), ("char_bigram_clean", result["clean_result"])]:
        print(f"\n--- {name} ---")
        for basis_name, basis in [("原始样本口径(188)", res["aggregate_sample_level"]), ("独立场景口径(47)", res["aggregate_scenario_level"])]:
            print(f"  {basis_name}:")
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                print(f"    K={k:>2}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}")
    print(f"\n社保补偿条款排名: {result['social_insurance_clause_ranks']}")
    print(f"工作地点条款排名: {result['workplace_clause_ranks']}")
    print(f"延迟支付(劳动报酬)条款排名: {result['delayed_payment_clause_ranks']}")
    c = result["baseline_vs_clean_comparison"]
    print(f"\nbaseline 找到但 clean 没找到: {len(c['baseline_found_clean_missed'])} 个 {c['baseline_found_clean_missed']}")
    print(f"clean 找到但 baseline 没找到: {len(c['clean_found_baseline_missed'])} 个 {c['clean_found_baseline_missed']}")
    print(f"两者都没找到: {len(c['neither_found'])} 个")


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = ["# BM25 文本预处理对照实验：char_bigram_baseline vs char_bigram_clean\n\n"]
    lines.append(f"运行时间（UTC）：{result['run_at']}\n\n")
    lines.append(
        f"BM25 参数：k1={result['bm25_k1']}, b={result['bm25_b']}；"
        f"candidate_k={result['candidate_k']}；final_top_k={result['final_top_k_values']}；"
        f"样本数={result['total_evaluable_samples']}；独立场景数={result['distinct_scenario_count']}\n\n"
    )
    lines.append("## 指标对照\n\n")
    lines.append("| 版本 | 口径 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|---|\n")
    for name, res in [("char_bigram_baseline", result["baseline_result"]), ("char_bigram_clean", result["clean_result"])]:
        for basis_name, basis in [("原始样本(188)", res["aggregate_sample_level"]), ("独立场景(47)", res["aggregate_scenario_level"])]:
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                lines.append(f"| {name} | {basis_name} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")

    lines.append("\n## 重点场景排名\n\n")
    lines.append(f"- 社保补偿条款：`{result['social_insurance_clause_ranks']}`\n")
    lines.append(f"- 工作地点条款：`{result['workplace_clause_ranks']}`\n")
    lines.append(f"- 延迟支付(劳动报酬)条款：`{result['delayed_payment_clause_ranks']}`\n")

    c = result["baseline_vs_clean_comparison"]
    lines.append("\n## baseline vs clean 差异\n\n")
    lines.append(f"- baseline 找到但 clean 没找到：{c['baseline_found_clean_missed']}\n")
    lines.append(f"- clean 找到但 baseline 没找到：{c['clean_found_baseline_missed']}\n")
    lines.append(f"- 两者都没找到：{c['neither_found']}\n")

    lines.append(
        "\n## 结论与限制\n\n详见对话中的文字分析（清洗是否改善指标、是否建议采用、限制）。"
        "本报告只保留可复现的真实数字。\n"
    )
    output_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    result = run()
    _print_summary(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"bm25_preprocessing_experiment_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")

    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print(f"简短报告已写出: {md_path}")


if __name__ == "__main__":
    main()
