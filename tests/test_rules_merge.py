"""rules/merge.py（merge_review_results）的单元测试。

核心语义：纯拼接，不覆盖、不去重、不比较——LLM 结果和规则结果都完整保留。
"""

from rules.merge import merge_review_results
from schemas import ReviewResult, ReviewSource, RiskLevel


def make_llm_result(clause_id: str, risk: bool = False) -> ReviewResult:
    return ReviewResult(
        clause_id=clause_id,
        risk=risk,
        risk_level=RiskLevel.HIGH if risk else RiskLevel.NONE,
        reason="LLM 判断理由",
        source=ReviewSource.LLM,
    )


def make_rule_result(clause_id: str, rule_id: str = "some_rule") -> ReviewResult:
    return ReviewResult(
        clause_id=clause_id,
        risk=True,
        risk_level=RiskLevel.HIGH,
        reason="规则判断理由",
        source=ReviewSource.RULE,
        rule_id=rule_id,
    )


def test_merge_is_pure_concatenation_length():
    llm_results = [make_llm_result(f"c{i}") for i in range(25)]
    rule_results = [make_rule_result("c5"), make_rule_result("c12")]

    merged = merge_review_results(llm_results, rule_results)

    # 25 条 LLM + 2 条规则 = 27 条，不是 25 条：规则命中不会顶替 LLM 结果
    assert len(merged) == 27


def test_llm_result_for_rule_matched_clause_is_not_removed():
    llm_results = [make_llm_result("c1", risk=False)]
    rule_results = [make_rule_result("c1")]

    merged = merge_review_results(llm_results, rule_results)

    assert len(merged) == 2
    sources = {r.source for r in merged}
    assert sources == {ReviewSource.LLM, ReviewSource.RULE}
    # 原始 LLM 结果对象本身没有被修改或替换
    assert merged[0] is llm_results[0]
    assert merged[0].risk is False


def test_merge_preserves_order_llm_first_then_rule():
    llm_results = [make_llm_result("c1"), make_llm_result("c2")]
    rule_results = [make_rule_result("c1")]

    merged = merge_review_results(llm_results, rule_results)

    assert merged == [llm_results[0], llm_results[1], rule_results[0]]


def test_empty_llm_results():
    rule_results = [make_rule_result("c1")]
    assert merge_review_results([], rule_results) == rule_results


def test_empty_rule_results():
    llm_results = [make_llm_result("c1")]
    assert merge_review_results(llm_results, []) == llm_results


def test_both_empty():
    assert merge_review_results([], []) == []


def test_no_deduplication_even_for_identical_rule_results():
    # 明确验证“不去重”：即便两条结果完全一样，也都保留
    r = make_rule_result("c1")
    merged = merge_review_results([], [r, r])
    assert len(merged) == 2
