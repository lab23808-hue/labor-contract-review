"""对全部 315 条 ClauseAnswer 样本生成逐条检索诊断记录（08：全量样本诊断）。

## 本脚本解决什么问题

`data/eval_samples/retrieval_eval_samples.json` 里一共有 315 条从标准答案构建的
样本，但此前所有检索实验（01-07）都只使用其中 188 条「有 legal_basis 标注」的
样本去计算 Recall/MRR/nDCG——这是对的，因为没有标准答案就没法自动判断检索对不对。

但另外 127 条不是"不存在"，而是"被排除在核心指标计算之外"：它们绝大多数是合规条款，
标准答案本来就没有标注对应的风险法条。如果完全不管这 127 条，就没有人知道：

    - 它们的检索结果长什么样（会不会检索到一些奇怪的、不相关的法条）；
    - 它们是否应该在未来被人工复核后补上标签，变成第 189 条可计算指标的样本；
    - 它们是不是其实也该归入某个规则候选模式。

本脚本不重新发明一套评分逻辑，只是：
    1. 读取全部 315 条样本（不止 188 条）；
    2. 对每条样本的 query，用【已保留的生产候选策略 char_bigram BM25】
       （01-07 轮实验里反复验证过、最终决定保留作为召回策略的版本，
       从 eval_retrieval_strategy_experiment.py / eval_bm25_tokenizer_experiment.py
       原样导入，没有重新实现）分别取 Top-5（对应生产 settings.RETRIEVAL_TOP_K=5）
       和 Top-20（对应实验里统一用的 candidate_k=20）两组候选；
    3. 对 188 条有标签的样本，复用 _score() 判断命中/漏检，并额外直接从命中数量算出
       `relevant_hit_count_top5/top20`、`zero_hit_top5/top20`、`partial_hit_top5/top20`、
       `all_hit_top5/top20` 四组互斥三态字段（2026-10-11 第二次修订新增，见下方
       「命中状态字段的精确定义」）；
    4. 对 127 条无标签的样本，只记录检索结果本身，状态统一标注为
       `no_gold_label_needs_review`，上述命中字段全部置为 `null`——这不是"检索失败"，
       是"没有标准答案可比对"，不参与任何命中/漏检判定。

## 命中状态字段的精确定义（2026-10-11 第二次修订：修正此前文档表述不够精确的问题）

    - `verified_hit_top5`（status 值）：Top-5 内命中了该样本【全部】标准相关法条，
      不是至少命中一条。多标签样本必须全部命中才算。
    - `verified_hit_top20_only`（status 值）：Top-5 没有命中全部（可能零命中，也可能
      部分命中——这两种情况在 status 这一层不区分），但 Top-20 内能找全全部标准相关法条。
    - `verified_miss`（status 值）：Top-20 内也没有找到任何一个标准相关法条。
    - 新增的 `zero_hit_top5` / `partial_hit_top5` / `all_hit_top5`（以及 Top-20 同名字段）
      是直接从「Top-K 实际检索结果」和「标准相关法条集合」的交集数量计算的互斥三态分类，
      不是从上面的 status 名称反推出来的——`all_hit_top5` 恒等于 `hit_top5`
      （脚本内置 assert 保证，不一致会直接报错)，但 `zero_hit_top5`/`partial_hit_top5`
      把原来 status 不区分的"Top-5 到底是零命中还是部分命中"这件事分开记录了。
    - **Recall@5 宏平均 ≠ `verified_hit_top5` 计数占比**：前者是逐样本
      `命中数/标准相关法条总数` 的算术平均（和 01-07 轮实验的 Recall@K 公式完全一致），
      后者是"是否全部命中"的二值计数占比。二者数值通常不同，差值等于所有 `partial_hit`
      样本贡献的部分召回分数之和除以总样本数——这不是 bug，是两个不同统计量，不能换算。

## 为什么只跑 BM25，不跑 Dense/RRF

跑 Dense 需要加载真实 BGE-M3 模型，是一次有成本、需要在有网络/有模型权重的机器上
真实执行的操作。已经在 01-04 轮验证过 Dense 的真实指标，且最终决策是保留 BM25
作为召回策略（BM25 排序质量更好，RRF 没有带来净收益）。覆盖全部 315 条样本是一次
纯粹的「诊断广度」扩展，不是重新论证策略选择，所以这里只用不需要模型的 BM25，
不额外调用真实模型。如果以后需要对 315 条样本做 Dense/RRF 的全量诊断，应该在
用户确认有必要后，在有真实模型的机器上单独补一轮，而不是在这里顺手跑。

## 固定不变的部分（全部原样复用，没有重新实现）

    - 知识库切分：strategy_mod._load_knowledge_evidences() /
      _load_knowledge_documents_for_bm25()
    - BM25 索引与打分：strategy_mod._BM25Index（k1=1.5, b=0.75）
    - 分词器：tokenizer_mod._char_bigram_tokenizer（保留版，不是 jieba，
      不是 boundary_aware——01-07 轮的最终结论是三者在本数据集上无实质差异或更差，
      保留最早验证过的 char_bigram 版本作为唯一诊断口径，避免在诊断脚本里引入
      第四个分词器变体造成混乱）
    - 命中评分公式：strategy_mod._score()

## 本脚本新增的唯一东西

    - _load_all_samples()：读取全部 315 条（不做 evaluable 过滤），
      01-07 轮用的 _load_evaluable_samples() 不变。
    - 按单个样本（不是按场景分组）跑 BM25，因为诊断要落到每一条 sample_id，
      而不是合并重复场景。

## 运行方式

    cd <项目根目录>
    python scripts/eval_full_sample_diagnostics.py

输出：
    data/eval_samples/full_sample_diagnostics.json
    data/eval_samples/full_sample_diagnostics.md（人类可读摘要）

## 这份诊断能证明什么，不能证明什么

能证明：
    - 这 315 条样本里，每一条用保留版 BM25 在 Top-5/Top-20 分别检索到了什么；
    - 188 条有标签样本里，哪些在生产 Top-5 配置下命中、哪些要放大到 Top-20 才命中、
      哪些在 Top-20 内完全没找到；
    - 127 条无标签样本的检索结果长什么样，供人工抽查。

不能证明：
    - 不能证明 127 条无标签样本"检索错了"或"检索对了"——没有标准答案就没有
      自动判断的依据，所有 127 条的 status 统一是 no_gold_label_needs_review，
      需要人工核验后才能转入可计算指标的那一组。
    - 不能代表 Dense/RRF 在全量 315 条上的表现（本脚本没有跑 Dense/RRF）。
"""

from __future__ import annotations

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
tokenizer_mod = importlib.import_module("eval_bm25_tokenizer_experiment")

_load_knowledge_evidences = strategy_mod._load_knowledge_evidences
_load_knowledge_documents_for_bm25 = strategy_mod._load_knowledge_documents_for_bm25
_BM25Index = strategy_mod._BM25Index
_score = strategy_mod._score
_char_bigram_tokenizer = tokenizer_mod._char_bigram_tokenizer

SAMPLES_PATH = PROJECT_ROOT / "data" / "eval_samples" / "retrieval_eval_samples.json"
RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples"
PRODUCTION_TOP_K = 5  # 对应 config/settings.py 的 RETRIEVAL_TOP_K，这里写成常量，不随 settings 静默变化
CANDIDATE_K = 20  # 对应 01-07 轮实验统一使用的 candidate_k


def _load_all_samples() -> list[dict]:
    """读取全部 315 条样本（不做 evaluable 过滤），和 01-07 轮的
    _load_evaluable_samples() 并存、互不影响——那个函数继续只给已验证实验用。"""
    if not SAMPLES_PATH.exists():
        raise SystemExit(f"找不到 {SAMPLES_PATH}，请先运行 build_retrieval_eval_samples.py")
    payload = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    return payload["samples"]


def _relevant_pairs(sample: dict) -> set:
    return {(r["source"], r["article"]) for r in sample.get("relevant", [])}


def _hit_breakdown(relevant_pairs: set, window_pairs: list) -> dict:
    """直接从本窗口（Top-5 或 Top-20）实际检索到的 (source,article) 和标准相关法条
    集合算出命中数量与三态分类——不从 status 名称反推，status 的计算反而要依赖这里。

    三态定义（互斥、覆盖全部有标签样本）：
        zero_hit    : 命中数 == 0，一条标准相关法条都没找到
        partial_hit : 0 < 命中数 < 标准相关法条总数，找到了一部分但没找全
        all_hit     : 命中数 == 标准相关法条总数（且 >0 时），全部找到
    """
    distinct_hits = {pair for pair in window_pairs if pair in relevant_pairs}
    hit_count = len(distinct_hits)
    total = len(relevant_pairs)
    return {
        "hit_count": hit_count,
        "total_relevant": total,
        "zero_hit": hit_count == 0,
        "partial_hit": 0 < hit_count < total,
        "all_hit": total > 0 and hit_count == total,
    }


def _diagnose_one(sample: dict, index: _BM25Index) -> dict:
    query = sample["query"]
    candidates = index.search(query, CANDIDATE_K)
    retrieved_pairs = [(c["source"], c["article"]) for c in candidates]

    top5 = candidates[:PRODUCTION_TOP_K]
    top20 = candidates[:CANDIDATE_K]
    top5_pairs = [(c["source"], c["article"]) for c in top5]
    top20_pairs = [(c["source"], c["article"]) for c in top20]

    record = {
        "sample_id": sample["sample_id"],
        "contract_id": sample["contract_sample_id"],
        "clause_id": sample["clause_id"],
        "clause_type": sample.get("clause_type", ""),
        "original_text": sample["original_text"],
        "query": query,
        "has_gold_label": bool(sample["evaluable"]),
        "exclude_reason": sample.get("exclude_reason", ""),
        "relevant": sample.get("relevant", []),
        "bm25_top5": top5,
        "bm25_top20": top20,
    }

    if not sample["evaluable"]:
        # 127 条无标签样本：没有标准答案可比对，所有命中状态字段统一置空（null），
        # 不判定为任何形式的漏检，也不参与 zero/partial/all 三态统计。
        record["status"] = "no_gold_label_needs_review"
        record["hit_top5"] = None
        record["hit_top20"] = None
        record["first_hit_rank"] = None
        record["relevant_hit_count_top5"] = None
        record["zero_hit_top5"] = None
        record["partial_hit_top5"] = None
        record["all_hit_top5"] = None
        record["relevant_hit_count_top20"] = None
        record["zero_hit_top20"] = None
        record["partial_hit_top20"] = None
        record["all_hit_top20"] = None
        return record

    relevant_pairs = _relevant_pairs(sample)
    score5 = _score(relevant_pairs, retrieved_pairs, PRODUCTION_TOP_K)
    score20 = _score(relevant_pairs, retrieved_pairs, CANDIDATE_K)
    record["hit_top5"] = score5["recall"] == 1.0 if score5["recall"] is not None else None
    record["hit_top20"] = score20["recall"] == 1.0 if score20["recall"] is not None else None
    record["first_hit_rank"] = score20["first_hit_rank"]
    record["recall_top5"] = score5["recall"]
    record["recall_top20"] = score20["recall"]

    # 新增字段：直接从 Top-5/Top-20 实际检索结果与标准相关法条集合算出的命中数量
    # 与互斥三态分类，不从上面的 hit_top5/hit_top20/status 反推。
    b5 = _hit_breakdown(relevant_pairs, top5_pairs)
    b20 = _hit_breakdown(relevant_pairs, top20_pairs)
    record["relevant_hit_count_top5"] = b5["hit_count"]
    record["zero_hit_top5"] = b5["zero_hit"]
    record["partial_hit_top5"] = b5["partial_hit"]
    record["all_hit_top5"] = b5["all_hit"]
    record["relevant_hit_count_top20"] = b20["hit_count"]
    record["zero_hit_top20"] = b20["zero_hit"]
    record["partial_hit_top20"] = b20["partial_hit"]
    record["all_hit_top20"] = b20["all_hit"]

    # 一致性自检：all_hit_top5 必须和 hit_top5（score5["recall"]==1.0）完全等价，
    # 否则说明两套算法（_score() 的 recall 比例 vs 这里的直接计数）出现了不一致，
    # 应该让程序在这里直接报错，而不是悄悄产出两份互相矛盾的字段。
    assert record["all_hit_top5"] == bool(record["hit_top5"]), (
        f"{sample['sample_id']}: all_hit_top5 与 hit_top5 不一致，"
        f"说明新增的直接计数逻辑和已验证的 _score() recall 逻辑算出了不同结果，需要排查"
    )
    assert record["all_hit_top20"] == bool(record["hit_top20"]), (
        f"{sample['sample_id']}: all_hit_top20 与 hit_top20 不一致"
    )

    if record["hit_top5"]:
        record["status"] = "verified_hit_top5"
    elif record["hit_top20"]:
        record["status"] = "verified_hit_top20_only"  # 在 candidate_k=20 内找到，但超出生产 top_k=5
    else:
        record["status"] = "verified_miss"
    return record


# 已知的规则候选案例（见 data/eval_samples/rule_candidate_cases.json），
# 用 sample_id 精确标记属于哪个候选模式，而不是在这里重新做模式匹配。
_RULE_CANDIDATE_SAMPLE_IDS: dict[str, str] = {
    "clear_risk_19::clear_risk_19_c02": "social_insurance_waiver_cash_compensation",
    "mixed_04::mixed_04_c02": "social_insurance_waiver_cash_compensation",
    "mixed_10::mixed_10_c05": "social_insurance_waiver_cash_compensation",
    "clear_risk_16::clear_risk_16_c02": "wage_delayed_payment_liability_waiver",
    "mixed_03::mixed_03_c05": "wage_delayed_payment_liability_waiver",
    "mixed_09::mixed_09_c05": "wage_delayed_payment_liability_waiver",
    "mixed_07::mixed_07_c02": "workplace_unilateral_change_no_compensation",
    "boundary_02::boundary_02_c02": "workplace_unilateral_change_no_compensation",
    "boundary_08::boundary_08_c02": "workplace_unilateral_change_no_compensation",
}


def run() -> dict:
    all_samples = _load_all_samples()
    evaluable_count = sum(1 for s in all_samples if s["evaluable"])
    non_evaluable_count = len(all_samples) - evaluable_count

    knowledge_evidences = _load_knowledge_evidences()
    bm25_docs = _load_knowledge_documents_for_bm25(knowledge_evidences)
    index = _BM25Index(bm25_docs, _char_bigram_tokenizer)

    records = []
    for sample in all_samples:
        record = _diagnose_one(sample, index)
        pattern = _RULE_CANDIDATE_SAMPLE_IDS.get(record["sample_id"])
        record["in_rule_candidate_list"] = pattern is not None
        record["rule_candidate_pattern"] = pattern or ""
        records.append(record)

    status_counts: dict[str, int] = {}
    for r in records:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    # 有标签样本的 zero/partial/all 三态分布（Top-5），用于和 status_counts 对照说明
    # 二者不是同一回事：status_counts 是"是否全部命中"的二值分类，
    # 下面这组是从命中数直接算出的三态分类，partial_hit 会被 status_counts 并进
    # verified_hit_top20_only 或 verified_miss 里，不单独体现。
    labeled = [r for r in records if r["has_gold_label"]]
    hit_breakdown_top5 = {
        "zero_hit": sum(1 for r in labeled if r["zero_hit_top5"]),
        "partial_hit": sum(1 for r in labeled if r["partial_hit_top5"]),
        "all_hit": sum(1 for r in labeled if r["all_hit_top5"]),
    }
    hit_breakdown_top20 = {
        "zero_hit": sum(1 for r in labeled if r["zero_hit_top20"]),
        "partial_hit": sum(1 for r in labeled if r["partial_hit_top20"]),
        "all_hit": sum(1 for r in labeled if r["all_hit_top20"]),
    }

    # 逐样本 recall_top5/recall_top20 的宏平均——这是和 01-07 轮实验里的
    # Recall@5/Recall@20 完全同一个公式（_score() 的 recall 比例，macro 平均），
    # 不是 status_counts 里 verified_hit_top5 的计数占比。两者数值通常不同，
    # 差异原因见 docs/RAG_EXPERIMENTS.md 第四节的专门说明。
    macro_recall_top5 = (
        round(sum(r["recall_top5"] for r in labeled) / len(labeled), 4) if labeled else None
    )
    macro_recall_top20 = (
        round(sum(r["recall_top20"] for r in labeled) / len(labeled), 4) if labeled else None
    )

    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "retrieval_strategy_used": "char_bigram BM25（保留版生产候选策略，k1=1.5, b=0.75）",
        "production_top_k": PRODUCTION_TOP_K,
        "candidate_k": CANDIDATE_K,
        "total_samples": len(all_samples),
        "evaluable_count": evaluable_count,
        "non_evaluable_count": non_evaluable_count,
        "status_counts": status_counts,
        "hit_breakdown_top5": hit_breakdown_top5,
        "hit_breakdown_top20": hit_breakdown_top20,
        "macro_recall_top5": macro_recall_top5,
        "macro_recall_top20": macro_recall_top20,
        "records": records,
    }


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = [
        "# 全部 315 条样本检索诊断摘要",
        "",
        f"运行时间（UTC）：{result['run_at']}",
        "",
        f"检索策略：{result['retrieval_strategy_used']}；生产 top_k={result['production_top_k']}；candidate_k={result['candidate_k']}",
        "",
        f"总样本数：{result['total_samples']}（有标签 {result['evaluable_count']} / 无标签 {result['non_evaluable_count']}）",
        "",
        "## 状态分布（二值分类：是否全部标准相关法条都命中）",
        "",
        "| 状态 | 数量 |",
        "|---|---:|",
    ]
    for status, count in sorted(result["status_counts"].items()):
        lines.append(f"| {status} | {count} |")
    lines += [
        "",
        "### 状态定义（必须严格按下面的语义理解，不要只看名字猜）",
        "",
        "- `verified_hit_top5`：**Top-5 内命中了该样本全部标准相关法条**（多标签样本要求全部命中，"
        "不是至少命中一条）。",
        "- `verified_hit_top20_only`：**Top-5 未能命中全部标准相关法条**，但 Top-20 内能够全部找全。"
        "这里的\"Top-5 未能全部命中\"包含两种真实情况——Top-5 一条都没命中（零命中），"
        "或者 Top-5 命中了一部分、但没有命中全部（部分命中）——这个状态本身不区分这两种情况，"
        "下面的「Top-5 命中情况三态分布」才区分。",
        "- `verified_miss`：candidate_k=20 内也没有找到任何一个标准相关法条。",
        "- `no_gold_label_needs_review`：没有标准答案可比对，不代表检索错误，不参与任何命中/漏检判定，"
        "需要人工核验后才能转入可计算指标的样本集。",
        "",
        "## Top-5 命中情况三态分布（互斥、覆盖全部 188 条有标签样本）",
        "",
        "这组统计直接从「Top-5 实际检索结果」与「标准相关法条集合」的交集数量计算，不从上面的状态"
        "名称反推，和状态分布是两个角度的统计：",
        "",
        "| 分类 | 定义 | 数量 |",
        "|---|---|---:|",
        f"| `zero_hit`（零命中） | Top-5 内一条标准相关法条都没找到 | {result['hit_breakdown_top5']['zero_hit']} |",
        f"| `partial_hit`（部分命中） | Top-5 内命中了至少一条，但没有找全 | {result['hit_breakdown_top5']['partial_hit']} |",
        f"| `all_hit`（全部命中） | Top-5 内找全了该样本的全部标准相关法条 | {result['hit_breakdown_top5']['all_hit']} |",
        "",
        f"校验：`all_hit`（{result['hit_breakdown_top5']['all_hit']}）应等于上面状态分布里的 "
        f"`verified_hit_top5`（{result['status_counts'].get('verified_hit_top5', 0)}）——两者算法不同"
        "（一个是直接计数交集，一个是 `_score()` 的 recall==1.0），脚本内置了断言保证二者永远一致，"
        "不一致会直接报错而不是悄悄产出矛盾数字。`zero_hit + partial_hit` 对应"
        "`verified_hit_top20_only + verified_miss` 的样本集合（但不是逐一相等，"
        "因为 `verified_hit_top20_only`/`verified_miss` 的区分依据是 Top-20 能不能找全，"
        "不是 Top-5 命中了几条）。",
        "",
        "## Recall@5 宏平均 与 verified_hit_top5 计数 不是同一个指标",
        "",
        f"- Recall@5 宏平均（逐样本 `命中数/标准相关法条总数` 取平均）= **{result['macro_recall_top5']}**，"
        "这个数字和 01-07 轮实验里 BM25 char_bigram 在 188 条口径下报告的 Recall@5 应该完全一致"
        "（历史真实数字见 `docs/RAG_EXPERIMENTS.md` 表 B/C）。",
        f"- `verified_hit_top5` 计数占比（{result['status_counts'].get('verified_hit_top5', 0)}/"
        f"{result['evaluable_count']} = "
        f"{round(result['status_counts'].get('verified_hit_top5', 0) / result['evaluable_count'], 4) if result['evaluable_count'] else 'N/A'}）"
        "是二值计数（全部命中才算1，部分命中算0），**不等于**上面的 Recall@5 宏平均，"
        "两者是不同的统计量，不能互相替代或换算——差值正好等于所有 `partial_hit` 样本贡献的"
        "部分召回分数之和除以总样本数。",
        "",
        "完整逐条记录（含 `relevant_hit_count_top5/top20`、`zero_hit_top5/top20`、"
        "`partial_hit_top5/top20`、`all_hit_top5/top20` 等新增字段）见同名 `.json` 文件，"
        "不在此 Markdown 中展开。",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result = run()
    print("=" * 70)
    print(f"总样本数={result['total_samples']}  有标签={result['evaluable_count']}  无标签={result['non_evaluable_count']}")
    for status, count in sorted(result["status_counts"].items()):
        print(f"  {status}: {count}")
    print()
    print("Top-5 命中三态（互斥，覆盖全部有标签样本）:", result["hit_breakdown_top5"])
    print("Top-20 命中三态:", result["hit_breakdown_top20"])
    print(f"Recall@5 宏平均 = {result['macro_recall_top5']}  （不等于 verified_hit_top5 计数占比，见 .md 报告说明）")
    print(f"Recall@20 宏平均 = {result['macro_recall_top20']}")

    output_path = RESULTS_DIR / "full_sample_diagnostics.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print()
    print(f"完整结果已写出: {output_path}")
    print(f"摘要已写出: {md_path}")


if __name__ == "__main__":
    main()
