"""rules/probation_duration.py 的单元测试。"""

from domain.rules.probation_duration import RULE_ID, check_probation_duration
from core import Clause, ReviewSource, RiskLevel


def make_clause(text: str, clause_id: str) -> Clause:
    return Clause(contract_id="c1", clause_id=clause_id, original_text=text, start_char=0, end_char=len(text))


# ---------- 固定期限：超期的各档 ----------

def test_one_year_contract_probation_exceeds_2_months():
    clauses = [
        make_clause("本合同期限为一年。", "c1"),
        make_clause("试用期为三个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    result = results[0]
    assert result.clause_id is None
    assert set(result.related_clause_ids) == {"c1", "c2"}
    assert result.risk is True
    assert result.risk_level == RiskLevel.HIGH
    assert result.source == ReviewSource.RULE
    assert result.rule_id == RULE_ID
    assert "2个月" in result.reason
    assert "3个月" in result.reason


def test_short_term_contract_probation_exceeds_1_month():
    clauses = [
        make_clause("合同期限6个月。", "c1"),
        make_clause("试用期2个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    assert "1个月" in results[0].reason


def test_long_term_contract_probation_exceeds_6_months():
    clauses = [
        make_clause("合同期限5年。", "c1"),
        make_clause("试用期为八个月。", "c2"),  # 超出 8 个月上限（8月由 arabic 混合无关，直接给中文数字）
    ]
    results = check_probation_duration(clauses)
    assert len(results) == 1
    assert "6个月" in results[0].reason


def test_contract_under_3_months_cannot_have_probation():
    clauses = [
        make_clause("合同期限2个月。", "c1"),
        make_clause("试用期为一个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    assert "不得约定试用期" in results[0].reason
    assert results[0].suggestion == "删除试用期约定。"


def test_task_based_contract_cannot_have_probation():
    clauses = [
        make_clause("本合同以完成一定的工作任务为期限。", "c1"),
        make_clause("试用期为一个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    assert "不得约定试用期" in results[0].reason


def test_non_fixed_term_probation_exceeds_6_months():
    clauses = [
        make_clause("本合同为无固定期限劳动合同。", "c1"),
        make_clause("试用期为八个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    assert "无固定期限" in results[0].reason
    assert "6个月" in results[0].reason


# ---------- 合规情况：不产出结果 ----------

def test_compliant_probation_produces_no_result():
    clauses = [
        make_clause("本合同期限为一年。", "c1"),
        make_clause("试用期为二个月。", "c2"),
    ]
    assert check_probation_duration(clauses) == []


def test_non_fixed_term_within_6_months_is_compliant():
    clauses = [
        make_clause("本合同为无固定期限劳动合同。", "c1"),
        make_clause("试用期为六个月。", "c2"),
    ]
    assert check_probation_duration(clauses) == []


# ---------- 提取不到就跳过，不猜测 ----------

def test_missing_duration_skips_check():
    clauses = [make_clause("试用期为三个月。", "c1")]
    assert check_probation_duration(clauses) == []


def test_missing_probation_skips_check():
    clauses = [make_clause("本合同期限为一年。", "c1")]
    assert check_probation_duration(clauses) == []


def test_no_clauses_returns_empty():
    assert check_probation_duration([]) == []


def test_date_range_duration_not_recognized_skips_check():
    # 日期区间表达的合同期限本来就不在 v1 覆盖范围内，应该提取不到、直接跳过
    clauses = [
        make_clause("本合同自2024年1月1日起至2025年1月1日止。", "c1"),
        make_clause("试用期为六个月。", "c2"),
    ]
    assert check_probation_duration(clauses) == []


# ---------- 回归测试：跨条款配对不能简单取"第一次出现的值"（P-28，见 ----------
# ---------- docs/PITFALLS.md）。对应 docs/EVAL_DIAGNOSTICS.md 实验6 真实 ----------
# ---------- 运行发现的 boundary_01 误报。 ----------
#
# 根因：原实现对"合同期限"和"试用期月数"分别独立地取条款列表里第一次能
# 提取到的值，不管两者是否来自同一条款——真实合同里常见的情况是"试用期
# 工资"条款原文也会复述一次试用期月数（比如"乙方试用期为3个月，试用期
# 工资为..."），这句话会被 _extract_probation_months 命中，抢在"合同期限
# 及试用期"这条真正描述期限的条款之前被当成"试用期月数"，和后面条款提取
# 到的"合同期限"错误配对，产生误判。


def test_unrelated_earlier_probation_mention_is_not_paired_with_later_duration_clause():
    """修复前：会把第一条里"试用期为3个月"（和合同期限无关的上下文提及）
    和第二条的"合同期限为一年"错误配对，算出 3个月 > 1年合同的2个月上限，
    误报违规。修复后：应该优先采信"合同期限"和"试用期"同时出现在同一条款
    里的配对（第二条自己就同时写了"一年"和"二个月"，2个月没有超过上限），
    不产出结果。
    """
    clauses = [
        make_clause("乙方试用期为3个月，试用期工资为正式工资标准的百分之八十。", "c1"),
        make_clause("本合同期限为一年。乙方试用期为二个月。", "c2"),
    ]
    assert check_probation_duration(clauses) == []


def test_same_clause_pairing_still_detects_real_violation_despite_unrelated_distractor():
    """同样有一条"无关的试用期提及"在前面干扰，但这次同条款里真正配对的
    期限+试用期确实违规（2年期合同最长2个月，约定了3个月）——修复不能把
    真实违规也一起隐藏掉。
    """
    clauses = [
        make_clause("乙方试用期为1个月，试用期工资为正式工资标准的百分之九十。", "c1"),
        make_clause("本合同期限为二年。乙方试用期为三个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    assert set(results[0].related_clause_ids) == {"c2"}
    assert "2个月" in results[0].reason
    assert "3个月" in results[0].reason


def test_no_single_clause_has_both_falls_back_to_cross_clause_scan():
    """没有任何一条条款同时包含期限和试用期信息时，退回旧的"分别取第一次
    提取到的值"逐条款扫描逻辑——这是现有全部其它测试用例的写法，必须保持
    不变，确认修复没有破坏这个分支。
    """
    clauses = [
        make_clause("本合同期限为一年。", "c1"),
        make_clause("试用期为三个月。", "c2"),
    ]
    results = check_probation_duration(clauses)

    assert len(results) == 1
    assert set(results[0].related_clause_ids) == {"c1", "c2"}


def test_multiple_same_clause_pairs_use_the_first_one_in_order():
    """如果真的有多条条款各自都同时写了期限+试用期（不常见，但要有确定的
    行为），采用条款顺序里第一条出现的配对，不做更复杂的歧义消解。
    """
    clauses = [
        make_clause("本合同期限为一年。乙方试用期为二个月。", "c1"),  # 合规，2<=2
        make_clause("本合同期限为五年。乙方试用期为八个月。", "c2"),  # 如果被采用会违规
    ]
    assert check_probation_duration(clauses) == []
