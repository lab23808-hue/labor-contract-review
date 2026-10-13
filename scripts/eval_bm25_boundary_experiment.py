"""BM25 字符二元分词的跨空白边界处理控制变量实验。

【要解决的问题】
    真实代码检查（eval_bm25_tokenizer_experiment.py::_char_bigram_tokenizer）
    确认过：该函数先把空白字符整体过滤掉，再对剩下的字符序列逐一配对成
    相邻二元组：

        chars = [c for c in text if not c.isspace()]
        return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]

    过滤空白之后，原本被换行/空格隔开的两个字符会被当成"相邻"，拼出一个
    原文里并不真实连续出现的 token。例如：

        "工作地点\n乙方应当服从安排"
        → 去空白后变成 "工作地点乙方应当服从安排"
        → 产生 "点乙" 这种跨越了原来的换行边界的伪 token。

    本轮只验证一件事：**只改变"是否允许二元组跨越空白边界"这一个变量**，
    分词算法本身（相邻两字符配对）完全不变，看检索指标会不会因此改善——
    不预先假定"消除伪 token 肯定更好"，因为这类伪 token 虽然是"噪声"，但
    也可能在某些场景里恰好贡献了意外有用的匹配信号，所以必须用真实指标说话。

【两个版本的实现差异】
    A. char_bigram_baseline：
        直接 import eval_bm25_tokenizer_experiment.py 里已经验证过的
        `_char_bigram_tokenizer`，不做任何修改——和上两轮实验里的
        baseline 组逐字相同。
    B. char_bigram_boundary_aware：
        先按连续空白把文本切成若干片段（`re.split(r"\\s+", text)`），再对
        每个片段**单独**生成字符二元组，最后把各片段的 token 列表拼接起来。
        片段内部的配对公式和 baseline 完全一样（相邻两字符配对），复用的是
        baseline 里构造 bigram 的那一行公式本身（`_bigram_pairs()`），不是
        重新发明一套算法。
        **边界情况**：如果某个片段去空白后只有 0 或 1 个字符，不产生任何
        token——不像 baseline 对"整段文本长度<=1"时会把那个孤立字符原样
        当成一个"token"返回（baseline 里 `len(chars) <= 1: return chars`
        这一行），这里**不**复用那条兜底逻辑，因为题目明确要求"不能为了保留
        这些单字符而临时引入其他类型的 token"——如果照搬 baseline 的兜底
        行为，会在几乎每个空白边界旁都新造出大量单字符 unigram token，这
        本身就是一种新的 token 类型，和"只改变跨边界处理方式"这个单一变量
        的实验设计相违背。

【固定不变 vs 唯一改变的变量】
    固定：query 原文、相关法条标签、知识库文本和切分结果及元数据、BM25
         参数（k1=1.5, b=0.75）、candidate_k=20、final_top_k={5,10,20}、
         指标计算公式和两套评估口径——全部直接从
         eval_retrieval_strategy_experiment.py / eval_bm25_tokenizer_experiment.py
         import 过来，不重写、不新增抽象。
    唯一改变：字符二元组是否允许跨越空白边界生成。不顺带清理标点（上一轮
    `char_bigram_clean` 已经单独测过标点/空白清理，这轮不重复引入那个变量）、
    不改数字处理方式、不改 query、不调 BM25 参数、不换知识库切分方式。

【运行前的前置核实】
    BM25 实验本身不需要加载 BGE-M3，但"两组结果能不能和前几轮直接比较"
    依赖一个前提：这次用的知识库切片内容，要和前几轮/正式环境里的内容一致。
    这里直接复用 eval_retrieval_strategy_experiment.py::
    `_verify_knowledge_base_against_official_db()`做同样的只读核验（对比
    官方 Chroma 实际存着的切片内容），核验结果会打印出来、写进输出 JSON，
    **核验不通过时会在报告里明确说明，不会假装结果可比**。

【运行】
    python scripts/eval_bm25_boundary_experiment.py
    输出：
        data/eval_samples/results/bm25_boundary_experiment_<时间戳>.json
        data/eval_samples/results/bm25_boundary_experiment_<时间戳>.md

【这个实验能证明什么，不能证明什么】
    能证明：在"查询和知识库都用字符二元分词，参数、知识内容、评估口径全部
    固定"的前提下，消除跨空白边界伪 token 这一个改动，对本项目这 188 条
    样本/47 个场景的真实 Recall/MRR/nDCG 有没有、有多大影响。
    不能证明：这个结论能不能推广到别的知识库规模、别的语言风格的合同文本、
    或者别的分词方案（jieba、word-level 等）——那些是独立的变量，这次没有
    一起测。也不能仅凭某一个样本的改善就判定整体策略更优，必须看 47 个
    场景的整体分布（下面的逐场景比较会给出具体数字）。
"""

import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

# 直接复用前两轮已经验证过的样本加载/场景分组/知识库切分/BM25实现/评分
# 公式/官方库一致性核验/单分词器完整跑一遍的流程函数——不重新写一套。
strategy_mod = importlib.import_module("eval_retrieval_strategy_experiment")
tokenizer_mod = importlib.import_module("eval_bm25_tokenizer_experiment")

_load_evaluable_samples = strategy_mod._load_evaluable_samples
_build_scenarios = strategy_mod._build_scenarios
_load_knowledge_evidences = strategy_mod._load_knowledge_evidences
_load_knowledge_documents_for_bm25 = strategy_mod._load_knowledge_documents_for_bm25
_verify_knowledge_base_against_official_db = strategy_mod._verify_knowledge_base_against_official_db
CANDIDATE_K = strategy_mod.CANDIDATE_K
FINAL_TOP_KS = strategy_mod.FINAL_TOP_KS
BM25_K1 = tokenizer_mod.BM25_K1
BM25_B = tokenizer_mod.BM25_B
_char_bigram_tokenizer = tokenizer_mod._char_bigram_tokenizer  # baseline，原样复用，不改一个字
_run_one_tokenizer = tokenizer_mod._run_one_tokenizer  # 建索引+47场景检索+两套口径指标

RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples" / "results"
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _bigram_pairs(chars: list[str]) -> list[str]:
    """和 baseline `_char_bigram_tokenizer` 里构造 bigram 的那一行公式完全
    相同：相邻两个字符配成一个 token。**不包含 baseline 的"长度<=1 时原样
    返回字符列表"这条兜底分支**——这是本脚本唯一一处和 baseline 不同的底层
    行为，原因见文件顶部说明（避免在分段场景里新造出单字符 token 这一种
    新的 token 类型）。输入：一个片段去空白后的字符列表；输出：该片段内部
    的二元 token 列表，长度<2 时返回空列表。
    """
    if len(chars) < 2:
        return []
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def _char_bigram_boundary_aware_tokenizer(text: str) -> list[str]:
    """按连续空白切分文本成片段，每个片段内部单独生成字符二元组，不跨片段
    配对。输入：原始文本；输出：所有片段的 token 拼接起来的列表。
    """
    tokens: list[str] = []
    for segment in _WHITESPACE_RUN_RE.split(text):
        chars = [c for c in segment if not c.isspace()]
        tokens.extend(_bigram_pairs(chars))
    return tokens


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

    # ---- 前置核实：这次用的知识片段内容是否和官方库一致，决定结果能不能和前几轮直接比较 ----
    kb_consistency = _verify_knowledge_base_against_official_db(knowledge_evidences)
    if kb_consistency["checked"]:
        if kb_consistency["content_match_exactly"]:
            print(f"知识库一致性核验通过：本次用的 {kb_consistency['official_doc_count']} 个切片内容与官方 Chroma 完全一致，结果可以和前几轮直接比较。")
        else:
            print("知识库一致性核验未通过，本次结果**不能**视为和前几轮直接可比：")
            for p in kb_consistency["problems"]:
                print("  -", p)
    else:
        print(f"知识库一致性核验未能执行（{kb_consistency['reason']}）——本次无法确认与前几轮是否可比，请对比时保持谨慎。")

    print("\n运行 char_bigram_baseline（原版，不改）...")
    baseline_result = _run_one_tokenizer("char_bigram_baseline", _char_bigram_tokenizer, scenarios, bm25_docs)

    print("运行 char_bigram_boundary_aware（按空白分段后段内配对，不跨边界）...")
    boundary_result = _run_one_tokenizer("char_bigram_boundary_aware", _char_bigram_boundary_aware_tokenizer, scenarios, bm25_docs)

    # ---- 重点场景：社保补偿 / 工作地点 / 延迟支付（劳动报酬）----
    def _scenario_ranks(predicate) -> dict:
        out = {}
        for name, res in [("char_bigram_baseline", baseline_result), ("char_bigram_boundary_aware", boundary_result)]:
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

    # ---- baseline vs boundary_aware：逐场景、逐法条比较排名变化和命中变化 ----
    base_by_key = {(sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc for sc in baseline_result["scenarios"]}
    bnd_by_key = {(sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc for sc in boundary_result["scenarios"]}

    baseline_only, boundary_only, both, neither = [], [], [], []
    rank_changes = []
    for key in base_by_key:
        rel = set(key[1])
        base_cands = [(c["source"], c["article"]) for c in base_by_key[key]["candidates"]]
        bnd_cands = [(c["source"], c["article"]) for c in bnd_by_key[key]["candidates"]]
        base_rank = {pair: i + 1 for i, pair in enumerate(base_cands)}
        bnd_rank = {pair: i + 1 for i, pair in enumerate(bnd_cands)}
        base_hits = set(base_cands) & rel
        bnd_hits = set(bnd_cands) & rel
        for art in rel:
            in_base, in_bnd = art in base_hits, art in bnd_hits
            entry = {"query": key[0][:30], "article": list(art)}
            if in_base and not in_bnd:
                baseline_only.append(entry)
            elif in_bnd and not in_base:
                boundary_only.append(entry)
            elif in_base and in_bnd:
                both.append(entry)
                br, nr = base_rank.get(art), bnd_rank.get(art)
                if br != nr:
                    rank_changes.append({"query": key[0][:30], "article": list(art), "baseline_rank": br, "boundary_aware_rank": nr})
            else:
                neither.append(entry)

    comparison = {
        "baseline_found_boundary_aware_missed": baseline_only,
        "boundary_aware_found_baseline_missed": boundary_only,
        "both_found_count": len(both),
        "neither_found": neither,
        "rank_changes_among_both_found": rank_changes,
    }

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "bm25_boundary_experiment",
        "versions_compared": ["char_bigram_baseline", "char_bigram_boundary_aware"],
        "bm25_k1": BM25_K1,
        "bm25_b": BM25_B,
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "total_evaluable_samples": len(evaluable),
        "distinct_scenario_count": len(scenarios),
        "knowledge_base_consistency": kb_consistency,
        "baseline_result": baseline_result,
        "boundary_aware_result": boundary_result,
        "social_insurance_clause_ranks": social_insurance_ranks,
        "workplace_clause_ranks": workplace_ranks,
        "delayed_payment_clause_ranks": delayed_payment_ranks,
        "baseline_vs_boundary_aware_comparison": comparison,
    }
    return result


def _print_summary(result: dict) -> None:
    print("=" * 78)
    print(f"candidate_k={result['candidate_k']}  final_top_k={result['final_top_k_values']}  bm25(k1={result['bm25_k1']}, b={result['bm25_b']})")
    print(f"样本数={result['total_evaluable_samples']}  独立场景数={result['distinct_scenario_count']}")
    print(f"知识库一致性核验: {result['knowledge_base_consistency']}")
    for name, res in [("char_bigram_baseline", result["baseline_result"]), ("char_bigram_boundary_aware", result["boundary_aware_result"])]:
        print(f"\n--- {name} ---")
        for basis_name, basis in [("原始样本口径(188)", res["aggregate_sample_level"]), ("独立场景口径(47)", res["aggregate_scenario_level"])]:
            print(f"  {basis_name}:")
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                print(f"    K={k:>2}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}")
    print(f"\n社保补偿条款排名: {result['social_insurance_clause_ranks']}")
    print(f"工作地点条款排名: {result['workplace_clause_ranks']}")
    print(f"延迟支付(劳动报酬)条款排名: {result['delayed_payment_clause_ranks']}")
    c = result["baseline_vs_boundary_aware_comparison"]
    print(f"\nbaseline 找到但 boundary_aware 没找到: {len(c['baseline_found_boundary_aware_missed'])} 个 {c['baseline_found_boundary_aware_missed']}")
    print(f"boundary_aware 找到但 baseline 没找到: {len(c['boundary_aware_found_baseline_missed'])} 个 {c['boundary_aware_found_baseline_missed']}")
    print(f"两者都没找到: {len(c['neither_found'])} 个")
    print(f"两者都找到但排名发生变化: {len(c['rank_changes_among_both_found'])} 处")
    for ch in c["rank_changes_among_both_found"]:
        print("  ", ch)


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = ["# BM25 字符二元分词跨空白边界处理对照实验：char_bigram_baseline vs char_bigram_boundary_aware\n\n"]
    lines.append(f"运行时间（UTC）：{result['run_at']}\n\n")
    lines.append(
        f"BM25 参数：k1={result['bm25_k1']}, b={result['bm25_b']}；"
        f"candidate_k={result['candidate_k']}；final_top_k={result['final_top_k_values']}；"
        f"样本数={result['total_evaluable_samples']}；独立场景数={result['distinct_scenario_count']}\n\n"
    )
    lines.append(f"知识库一致性核验：`{result['knowledge_base_consistency']}`\n\n")

    lines.append("## 指标对照\n\n")
    lines.append("| 版本 | 口径 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|---|\n")
    for name, res in [("char_bigram_baseline", result["baseline_result"]), ("char_bigram_boundary_aware", result["boundary_aware_result"])]:
        for basis_name, basis in [("原始样本(188)", res["aggregate_sample_level"]), ("独立场景(47)", res["aggregate_scenario_level"])]:
            for k in result["final_top_k_values"]:
                agg = basis[str(k)]
                lines.append(f"| {name} | {basis_name} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")

    lines.append("\n## 重点场景排名\n\n")
    lines.append(f"- 社保补偿条款：`{result['social_insurance_clause_ranks']}`\n")
    lines.append(f"- 工作地点条款：`{result['workplace_clause_ranks']}`\n")
    lines.append(f"- 延迟支付(劳动报酬)条款：`{result['delayed_payment_clause_ranks']}`\n")

    c = result["baseline_vs_boundary_aware_comparison"]
    lines.append("\n## baseline vs boundary_aware 差异\n\n")
    lines.append(f"- baseline 找到但 boundary_aware 没找到：{c['baseline_found_boundary_aware_missed']}\n")
    lines.append(f"- boundary_aware 找到但 baseline 没找到：{c['boundary_aware_found_baseline_missed']}\n")
    lines.append(f"- 两者都没找到：{c['neither_found']}\n")
    lines.append(f"- 两者都找到但排名变化：{c['rank_changes_among_both_found']}\n")

    lines.append(
        "\n## 结论与限制\n\n详见对话中的文字分析（是否消除了跨边界 token、指标是否改善、"
        "是否建议采用、限制）。本报告只保留可复现的真实数字。\n"
    )
    output_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    result = run()
    _print_summary(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"bm25_boundary_experiment_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")

    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print(f"简短报告已写出: {md_path}")


if __name__ == "__main__":
    main()
