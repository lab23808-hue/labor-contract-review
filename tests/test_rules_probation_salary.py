"""rules/probation_salary.py 的单元测试。"""

from rules.probation_salary import RULE_ID, check_probation_salary
from schemas import Clause, ReviewSource, RiskLevel


def make_clause(text: str, clause_id: str = "clause_001") -> Clause:
    return Clause(contract_id="c1", clause_id=clause_id, original_text=text, start_char=0, end_char=len(text))


def test_detects_cn_percentage_below_80():
    clause = make_clause("乙方试用期为三个月，试用期工资为正式工资标准的百分之五十。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    result = results[0]
    assert result.clause_id == "clause_001"
    assert result.risk is True
    assert result.risk_level == RiskLevel.HIGH
    assert result.source == ReviewSource.RULE
    assert result.rule_id == RULE_ID
    assert "50" in result.reason
    assert result.legal_basis == ["《劳动合同法》第二十条"]


def test_detects_arabic_percentage_below_80():
    clause = make_clause("试用期工资按正式工资的65%执行。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    assert "65" in results[0].reason


def test_detects_two_digit_cn_percentage():
    clause = make_clause("试用期工资为正式工资标准的百分之七十五。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    assert "75" in results[0].reason


def test_exactly_80_percent_is_compliant():
    clause = make_clause("试用期工资为正式工资标准的百分之八十。")
    assert check_probation_salary([clause]) == []


def test_above_80_percent_is_compliant():
    clause = make_clause("试用期工资为正式工资标准的百分之九十。")
    assert check_probation_salary([clause]) == []


def test_no_percentage_mentioned_returns_empty():
    clause = make_clause("乙方试用期为三个月，试用期工资面议。")
    assert check_probation_salary([clause]) == []


def test_percentage_far_from_probation_salary_keyword_not_matched():
    # “百分之十”离“试用期工资”太远（超过 20 字符窗口），不应该被误判成试用期工资比例
    clause = make_clause("试用期工资另行约定，" + "本条款与年终奖金无关，" * 3 + "年终奖金为基本工资的百分之十。")
    assert check_probation_salary([clause]) == []


def test_only_flags_matching_clause_among_many():
    clauses = [
        make_clause("竞业限制条款，与试用期无关。", clause_id="c1"),
        make_clause("试用期工资为正式工资标准的百分之五十。", clause_id="c2"),
        make_clause("工作地点条款，与试用期无关。", clause_id="c3"),
    ]
    results = check_probation_salary(clauses)

    assert len(results) == 1
    assert results[0].clause_id == "c2"


def test_no_clauses_returns_empty():
    assert check_probation_salary([]) == []


# ---------- 回归测试：百分比正则遗漏"零"（P-27，见 docs/PITFALLS.md） ----------
# 根因：_PERCENT_RE 的中文数字字符类是 [一二三四五六七八九十百]，不包含"零"，
# 所以"百分之零"（0%，比任何法定下限都低，是最明显的风险）反而被规则直接
# 跳过——_extract_percent 返回 None，check_probation_salary 当作"没写比例"
# 处理，造成漏检。修复前，下面三个 test_detects_* 用例应该失败。


def test_detects_cn_zero_percent():
    clause = make_clause("乙方试用期为3个月，试用期工资为正式工资标准的百分之零。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    assert results[0].risk is True
    assert "0" in results[0].reason


def test_detects_arabic_zero_percent():
    clause = make_clause("试用期工资按正式工资的0%执行。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    assert "0" in results[0].reason


def test_detects_fullwidth_percent_sign_zero():
    # 任务里特别点名要检查的全角百分号写法："0％"
    clause = make_clause("试用期工资按正式工资的0％执行。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    assert "0" in results[0].reason


def test_detects_fullwidth_percent_sign_below_80():
    # 全角百分号不止 0% 要支持，65％ 这种常规低于 80% 的场景也要支持
    clause = make_clause("试用期工资按正式工资的65％执行。")
    results = check_probation_salary([clause])

    assert len(results) == 1
    assert "65" in results[0].reason


# ---------- 边界测试：加入"零"之后不能把正常比例误判为风险 ----------


def test_adding_zero_support_does_not_break_80_percent_compliant():
    clause = make_clause("试用期工资为正式工资标准的百分之八十。")
    assert check_probation_salary([clause]) == []


def test_adding_zero_support_does_not_break_100_percent_compliant():
    clause = make_clause("试用期工资为正式工资标准的百分之一百。")
    assert check_probation_salary([clause]) == []


def test_zero_in_unrelated_context_not_mistaken_for_percent():
    # 条款里出现"零"但不是在"试用期工资...百分之零"这个固定搭配里，
    # 不应该被误判成 0% 试用期工资。
    clause = make_clause("试用期工资另行约定，公司注册资本零点五亿元。")
    assert check_probation_salary([clause]) == []
