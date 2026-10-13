"""诊断实验的核心逻辑（纯函数，不做 I/O 入口——入口在
`scripts/run_eval_samples.py`）。

本文件只实现在本沙箱里**真正能跑**的两个实验：

- 实验 1：知识库覆盖检查（纯文本比对，不需要 chromadb）。
- 实验 6（规则部分）：用 50 份评估合同的标准答案直接构造 `schemas.Clause`
  对象（绕开需要 `langchain_text_splitters` 的 `ClauseSplitter`），喂给
  **真实的** `rules.RuleChecker`，和 `rule_expectations.json` 里的预期比对，
  算出规则层的漏检/误报——这是真实生产代码 `rules/checker.py` 跑出来的结果，
  不是模拟。

实验 2（条款切分）、实验 3/4/5（RAG/LLM）、实验 6 里需要 LLM 结果的部分、
实验 7（端到端）本沙箱无法真实运行（缺 langchain_text_splitters / chromadb /
openai / langgraph / 网络），这里不提供"降级模拟"版本——降级模拟会被误读成
真实结果，这正是任务要求明确禁止的事（"不得使用 FakeLLM 的结果冒充真实模型
审查效果"）。这些实验的脚本和本地运行命令见
`scripts/run_eval_samples.py` 和 `docs/EVAL_DIAGNOSTICS.md`。
"""

import re
from pathlib import Path
from typing import Optional

from evaluation.schemas import ContractAnswer

# 和 scripts/validate_knowledge_base.py 保持一致的切分正则（见该文件说明：
# 不 import rag/knowledge_loader.py，因为它的模块顶层需要
# langchain_text_splitters，这里要的只是"这个条号是否存在于知识库文本里"，
# 不需要真的切分成 Evidence）。
_CN_DIGITS = "一二三四五六七八九十百千零〇两"
_ARTICLE_RE = re.compile(rf"^[ \t　]*(第[{_CN_DIGITS}\d]+条)(?!的)", re.MULTILINE)


def _extract_article_labels(text: str) -> set[str]:
    return {m.group(1) for m in _ARTICLE_RE.finditer(text)}


def _parse_citation(citation: str) -> Optional[str]:
    """从 "《劳动合同法》第二十条" 这样的引用字符串里提取 "第二十条" 这部分，
    用于和知识库里的条号做匹配。提取不出来就返回 None（不猜测）。
    """
    match = re.search(rf"第[{_CN_DIGITS}\d]+条", citation)
    return match.group(0) if match else None


def experiment1_knowledge_coverage(answers: list[ContractAnswer], knowledge_dir: Path) -> dict:
    """实验 1：标准答案要求的法律依据，是否已经存在于知识库里。

    这里独立重新扫描知识库文本（不信任标准答案自己标注的
    `legal_basis_verified_in_sources` 字段），是为了让这个检查真正算一次
    独立验证，而不是在复述标注时已经声明过的结论。
    """
    kb_articles: set[str] = set()
    kb_files = sorted(knowledge_dir.glob("*.txt"))
    for f in kb_files:
        kb_articles |= _extract_article_labels(f.read_text(encoding="utf-8"))

    required_citations: set[str] = set()
    for contract in answers:
        for clause in contract.clauses:
            required_citations.update(clause.legal_basis)

    found, missing, unparsable = [], [], []
    for citation in sorted(required_citations):
        article = _parse_citation(citation)
        if article is None:
            unparsable.append(citation)
        elif article in kb_articles:
            found.append(citation)
        else:
            missing.append(citation)

    total = len(required_citations)
    return {
        "knowledge_base_files": [f.name for f in kb_files],
        "knowledge_base_article_count": len(kb_articles),
        "required_citation_total": total,
        "found_count": len(found),
        "found": found,
        "missing_count": len(missing),
        "missing": missing,
        "unparsable_count": len(unparsable),
        "unparsable": unparsable,
        "coverage_rate": round(len(found) / total, 4) if total else None,
    }


def experiment6_rule_layer_check(
    contracts_with_parts: list[tuple[ContractAnswer, list[dict]]],
) -> dict:
    """实验 6（规则部分）：用真实 RuleChecker 跑一遍，和 rule_expectations
    对比，统计规则独立发现的风险、漏检、误报。

    这里直接 import `rules`（纯 schemas 依赖，不需要 langchain/chromadb/
    openai），对每份合同把标准答案里的条款重新构造成真实 `schemas.Clause`
    对象（不是 fake，是生产代码 `rules.RuleChecker.check()` 实际接受的
    同一种类型），调用生产代码，得到的 `ReviewResult` 是规则引擎真实跑出来
    的结果。
    """
    from rules import RuleChecker
    from schemas import Clause

    checker = RuleChecker()

    contract_reports = []
    total_hits_matched = 0
    total_expected_hits = 0
    total_actual_hits = 0
    missed: list[dict] = []  # 规则漏检：rule_expectation 认为规则应该命中，但实际没命中——真正的规则 bug/回归
    false_positive: list[dict] = []  # 规则误报：没预期命中但命中了
    known_limitation_gap: list[dict] = []  # 已知可接受的规则能力缺口：
    # 标准答案里 risk=True（法律上真的有风险），但 rule_expectation.expected_hit=False
    # （我们在设计条款素材库时就已经知道、并记录了"这条规则目前的实现能力够不到这种情况"），
    # 且实际确实没命中——这不是"规则坏了"，是"规则从一开始就没打算覆盖这种写法"，
    # 两者必须分开统计，否则会把"已知且被记录的能力边界"误报成"新发现的 bug"。

    for contract, parts in contracts_with_parts:
        clauses = [
            Clause(
                contract_id=contract.sample_id,
                clause_id=c.clause_id,
                clause_type=c.clause_type,
                original_text=c.original_text,
                start_char=c.start_char,
                end_char=c.end_char,
                hierarchy_level=0,
            )
            for c in contract.clauses
        ]
        results = checker.check(clauses)

        # 规则结果可能是 clause_id（单条款问题）或 related_clause_ids（跨条款
        # 问题）——建立"这条结果关联了哪些 clause_id"的集合，用于和期望比对。
        hit_clause_ids: set[str] = set()
        for r in results:
            if r.clause_id is not None:
                hit_clause_ids.add(r.clause_id)
            hit_clause_ids.update(r.related_clause_ids)

        expectations = {c.clause_id: parts[i]["rule_expectation"] for i, c in enumerate(contract.clauses)}
        ground_truth_risk = {c.clause_id: c.risk for c in contract.clauses}

        per_clause = []
        for clause_id, expectation in expectations.items():
            expected = expectation["expected_hit"]
            actual = clause_id in hit_clause_ids
            risk = ground_truth_risk[clause_id]
            total_expected_hits += int(expected)
            total_actual_hits += int(actual)
            if expected and actual:
                total_hits_matched += 1
            elif expected and not actual:
                missed.append({"sample_id": contract.sample_id, "clause_id": clause_id})
            elif not expected and actual:
                false_positive.append({"sample_id": contract.sample_id, "clause_id": clause_id})
            elif not expected and not actual and risk:
                # expected_hit=False 是我们在素材库里主动标注的"规则做不到"，
                # 不是本次运行发现的新问题，所以不计入 missed_count/recall 的
                # 分母——但必须单独列出来，否则"规则能力边界在哪"会被完全隐藏。
                known_limitation_gap.append(
                    {"sample_id": contract.sample_id, "clause_id": clause_id,
                     "expected_rule_id": expectation.get("expected_rule_id")}
                )
            per_clause.append(
                {
                    "clause_id": clause_id,
                    "expected_hit": expected,
                    "actual_hit": actual,
                    "ground_truth_risk": risk,
                }
            )

        contract_reports.append(
            {
                "sample_id": contract.sample_id,
                "rule_results_count": len(results),
                "per_clause": per_clause,
            }
        )

    return {
        "ruleset_version": checker.ruleset_version,
        "contracts_checked": len(contracts_with_parts),
        "total_expected_hits": total_expected_hits,
        "total_actual_hits": total_actual_hits,
        "total_matched": total_hits_matched,
        "missed_count": len(missed),
        "missed": missed,
        "false_positive_count": len(false_positive),
        "false_positive": false_positive,
        "known_limitation_gap_count": len(known_limitation_gap),
        "known_limitation_gap": known_limitation_gap,
        "recall": round(total_hits_matched / total_expected_hits, 4) if total_expected_hits else None,
        "precision": (
            round(total_hits_matched / total_actual_hits, 4) if total_actual_hits else None
        ),
        "contract_reports": contract_reports,
    }
