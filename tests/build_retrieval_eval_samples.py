"""构建"统一检索评估样本集"：把 50 份评估合同的 315 条 ClauseAnswer，
转成检索基线实验要用的标准样本格式，写到
data/eval_samples/retrieval_eval_samples.json。

为什么要先落盘成一个独立文件，而不是每次实验都重新生成：
    用户要求"同一个样本在所有实验中必须使用相同的 query 和相关法条标签"——
    如果每次跑实验都重新调用 generate_query()/重新解析 legal_basis，一旦以后
    generate_query() 或 clause_bank.py 的条款原型有改动，不同时间跑的实验会
    悄悄用上不同的 query/标签，没法比较。落盘成一份带时间戳的快照之后，
    后续所有检索实验都从这份文件读，不重新计算，除非显式重新运行本脚本。

每条样本至少包含：
    - sample_id：f"{contract_sample_id}::{clause_id}"，全局唯一
    - original_text：条款原文（来自标准答案，不是重新切分出来的）
    - query：调用**真实、未修改**的 agents.review_agent.generate_query()
      生成（和正式审查链路用的是同一份函数，不是自己另写一套近似逻辑）
    - legal_basis_raw：标准答案里原样的引用字符串列表，例如
      ["《劳动合同法》第二十条"]
    - relevant：解析后的结构化版本，每条是 {"source": "劳动合同法",
      "article": "第二十条", "raw": "《劳动合同法》第二十条"}——用于和
      Evidence.source/Evidence.article 做比对，不是字符串相等比较
    - evaluable：这条样本能不能用于检索基线评估
    - exclude_reason：evaluable=False 时，具体是因为什么原因被排除
      （没有 legal_basis / 引用解析失败 / 引用的法条当前知识库里没有），
      不是一个笼统的"跳过"

**不做的事**（刻意）：
    - 不猜测没有 legal_basis 的条款"应该"对应哪条法律依据——没有标注就是
      没有标注，evaluable=False，原因写清楚，绝不用模型自己猜一个塞进去。
    - 不认为"标准答案文字相似"等于"检索到了正确法律依据"——这里只负责
      产出 ground truth 标签，相似度判断是 eval_retrieval_baseline.py
      检索之后的事，不在本脚本里做。
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.review_agent import generate_query  # noqa: E402  （真实生产函数，未修改）
from config import settings  # noqa: E402
from evaluation.generate_contracts import build_all_contracts_with_parts  # noqa: E402
from schemas import Clause  # noqa: E402

OUTPUT_PATH = PROJECT_ROOT / "data" / "eval_samples" / "retrieval_eval_samples.json"

_CN_DIGITS = "一二三四五六七八九十百千零〇两"
# 标准答案里的引用格式固定是 "《书名》第X条"（已对 315 条标准答案实测验证过，
# 见 docs/EVAL_BASELINE.md 的记录），这里按同样的格式解析。
_CITATION_RE = re.compile(rf"《(.+?)》\s*(第[{_CN_DIGITS}0-9]+条)")
_ARTICLE_RE = re.compile(rf"第[{_CN_DIGITS}0-9]+条")


def _knowledge_base_articles() -> dict[str, set[str]]:
    """按文件名（= source）扫描 data/knowledge/*.txt，返回
    {source: {条号, ...}}，用于判断某条引用是否真的存在于当前知识库里。
    不依赖 Chroma/embedding，纯文本扫描，和 evaluation/diagnostics.py 里
    `_extract_article_labels()` 的做法一致，但这里按文件名分开统计，
    不是把所有文件的条号混成一个全局集合（否则不同法律文件的同一个条号
    会被误判成"存在"）。
    """
    result: dict[str, set[str]] = {}
    for f in sorted(settings.KNOWLEDGE_DIR.glob("*.txt")):
        result[f.stem] = set(_ARTICLE_RE.findall(f.read_text(encoding="utf-8")))
    return result


def _parse_citation(citation: str) -> tuple[str, str] | None:
    match = _CITATION_RE.match(citation.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def build_samples() -> list[dict]:
    kb_articles = _knowledge_base_articles()
    samples: list[dict] = []

    for contract, _parts in build_all_contracts_with_parts():
        for clause_answer in contract.clauses:
            clause = Clause(
                contract_id=contract.sample_id,
                clause_id=clause_answer.clause_id,
                clause_type=clause_answer.clause_type,
                original_text=clause_answer.original_text,
                start_char=clause_answer.start_char,
                end_char=clause_answer.end_char,
                hierarchy_level=0,
            )
            query = generate_query(clause)

            relevant: list[dict] = []
            evaluable = True
            reason = ""

            if not clause_answer.legal_basis:
                evaluable = False
                reason = "标准答案没有标注 legal_basis（通常是合规条款，没有对应的风险法条）"
            else:
                unparsable = []
                for cite in clause_answer.legal_basis:
                    parsed = _parse_citation(cite)
                    if parsed is None:
                        unparsable.append(cite)
                        continue
                    relevant.append({"source": parsed[0], "article": parsed[1], "raw": cite})

                if unparsable:
                    evaluable = False
                    reason = f"legal_basis 存在但无法按《书名》+第X条格式解析：{unparsable}"
                else:
                    not_in_kb = [
                        r for r in relevant
                        if r["article"] not in kb_articles.get(r["source"], set())
                    ]
                    if not_in_kb:
                        evaluable = False
                        reason = f"引用的法条当前知识库里没有（书名不匹配任何已加载文件，或条号不在该文件里）：{not_in_kb}"

            samples.append(
                {
                    "sample_id": f"{contract.sample_id}::{clause_answer.clause_id}",
                    "contract_sample_id": contract.sample_id,
                    "clause_id": clause_answer.clause_id,
                    "clause_type": clause_answer.clause_type,
                    "risk": clause_answer.risk,
                    "original_text": clause_answer.original_text,
                    "query": query,
                    "legal_basis_raw": clause_answer.legal_basis,
                    "relevant": relevant,
                    "evaluable": evaluable,
                    "exclude_reason": reason,
                }
            )

    return samples


def main() -> None:
    samples = build_samples()
    evaluable = [s for s in samples if s["evaluable"]]
    excluded = [s for s in samples if not s["evaluable"]]
    multi_label = [s for s in evaluable if len(s["relevant"]) > 1]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_retrieval_eval_samples.py",
        "query_function": "agents.review_agent.generate_query（真实生产函数，未修改）",
        "total_clauses": len(samples),
        "evaluable_count": len(evaluable),
        "excluded_count": len(excluded),
        "multi_label_count": len(multi_label),
        "coverage_rate": round(len(evaluable) / len(samples), 4) if samples else None,
        "samples": samples,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"总条款数: {len(samples)}")
    print(f"可评估（evaluable=True）: {len(evaluable)}（覆盖率 {payload['coverage_rate']:.2%}）")
    print(f"被排除: {len(excluded)}")
    reasons: dict[str, int] = {}
    for s in excluded:
        key = s["exclude_reason"].split("：")[0]
        reasons[key] = reasons.get(key, 0) + 1
    for reason, count in reasons.items():
        print(f"  - {reason}: {count}")
    print(f"多标签样本（一个条款对应多条法律依据）: {len(multi_label)}")
    print(f"\n已写出: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
