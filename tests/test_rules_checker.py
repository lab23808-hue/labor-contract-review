"""rules/checker.py（RuleChecker）的单元测试。

重点验证：RuleChecker 只根据 Clause 本身判断适用性，不依赖任何 LLM 结果或
"不确定"标记——接口签名上就不接收 llm_results，这里从行为上再确认一遍：
不管有没有命中规则的条款和没命中的条款混在一起，只有真正命中的才会有结果。
"""

from domain.rules.checker import RuleChecker
from core import Clause, ReviewSource


def make_clause(text: str, clause_id: str) -> Clause:
    return Clause(contract_id="c1", clause_id=clause_id, original_text=text, start_char=0, end_char=len(text))


def test_no_clauses_match_any_rule_returns_empty():
    clauses = [make_clause("工作地点为北京市。", "c1"), make_clause("竞业限制为二年。", "c2")]
    assert RuleChecker().check(clauses) == []


def test_only_matching_clauses_produce_results_others_ignored():
    clauses = [
        make_clause("工作地点为北京市。", "c1"),  # 不命中任何规则
        make_clause("试用期工资为正式工资标准的百分之五十。", "c2"),  # 命中 probation_salary
        make_clause("竞业限制为二年，无需支付经济补偿。", "c3"),  # 不命中任何规则
    ]
    results = RuleChecker().check(clauses)

    assert len(results) == 1
    assert results[0].clause_id == "c2"
    assert results[0].source == ReviewSource.RULE


def test_multiple_rules_can_each_contribute_results():
    clauses = [
        make_clause("本合同期限为一年。", "c1"),
        make_clause("试用期为三个月，试用期工资为正式工资标准的百分之五十。", "c2"),
    ]
    results = RuleChecker().check(clauses)

    # probation_salary 命中 c2（工资50%），probation_duration 命中期限+试用期组合（1年上限2个月，约定3个月超期）
    rule_ids = {r.rule_id for r in results}
    assert "probation_salary_below_80_percent" in rule_ids
    assert "probation_duration_exceeds_legal_cap" in rule_ids
    assert len(results) == 2


def test_does_not_take_llm_results_argument():
    # RuleChecker.check 的签名只接受 clauses，不接受 llm_results——
    # 这里用 25 个"看似都被 LLM 判过"的条款场景验证它完全不需要那份信息。
    clauses = [make_clause(f"第{i}条 无关内容", f"c{i}") for i in range(25)]
    clauses.append(make_clause("试用期工资为正式工资标准的百分之五十。", "c_hit"))

    results = RuleChecker().check(clauses)

    assert len(results) == 1
    assert results[0].clause_id == "c_hit"


def test_empty_clause_list_returns_empty():
    assert RuleChecker().check([]) == []
