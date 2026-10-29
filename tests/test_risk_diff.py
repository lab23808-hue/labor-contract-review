"""diff/risk_diff.py 的匹配/分类逻辑测试。

背景（见 docs 中本次修复的记录）：旧实现 `_result_key()` 对规则来源的结果
只用 `rule_id` 作为匹配键，`risk_diff()` 内部又是用字典推导式
`{_result_key(r): r for r in results}` 构建 v1_by_key/v2_by_key——当同一条
规则命中了多个不同条款（例如 probation_salary 规则在多处"试用期工资"条款
都命中）时，这些结果会共享同一个 rule_id，字典推导式会用后面的结果静默
覆盖前面的，导致同一规则命中的多个条款在 V1/V2 Diff 中只剩一条，其余条款
的风险结果被悄悄丢弃——用户看到的 Diff 会少报已存在的风险。

本文件覆盖：
    1. 两个不同 clause_id 命中同一个 rule_id 时，两条结果都必须出现在 Diff 里
       （直接复现并验证修复前述 bug）。
    2. V1/V2 都存在"相同规则、相同条款"的结果时，必须被当成同一条、正确匹配。
    3. 同一规则在 V1/V2 中命中的条款发生变化（不是同一个 clause_id）时，
       不能被静默丢弃——必须分别体现为"V1 这条没了"和"V2 这条是新出现的"。
    4. 原有 LLM 来源结果按 clause_id 匹配的行为不能被破坏。
    5.（补充）规则来源但没有单一 clause_id、只有 related_clause_ids 的跨条款
       问题（如 probation_duration），匹配逻辑也不应该因为 clause_id 为 None
       就把不同的 related_clause_ids 组合混为一谈。
"""

from domain.diff.risk_diff import risk_diff
from core import ReviewResult, ReviewSource, RiskLevel


def _llm_result(clause_id: str, risk_level: RiskLevel, reason: str = "r") -> ReviewResult:
    return ReviewResult(
        clause_id=clause_id,
        risk=risk_level != RiskLevel.NONE,
        risk_level=risk_level,
        reason=reason,
        source=ReviewSource.LLM,
    )


def _rule_result(
    rule_id: str,
    risk_level: RiskLevel,
    clause_id: str | None = None,
    related_clause_ids: list[str] | None = None,
    reason: str = "r",
) -> ReviewResult:
    return ReviewResult(
        clause_id=clause_id,
        related_clause_ids=related_clause_ids or [],
        risk=risk_level != RiskLevel.NONE,
        risk_level=risk_level,
        reason=reason,
        source=ReviewSource.RULE,
        rule_id=rule_id,
    )


class TestSameRuleDifferentClauses:
    """1. 两个不同 clause_id 命中同一个 rule_id 时，两条结果都要参与 Diff。"""

    def test_both_clauses_present_in_v1_only_produce_two_unmatched_entries(self):
        v1_results = [
            _rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c1"),
            _rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c2"),
        ]
        entries = risk_diff(v1_results, [])

        # 旧实现会因为 rule_id 相同、字典推导式覆盖，只剩 1 条 entry——
        # 这里必须是 2 条，且都标记为 unmatched（V2 没有对应结果）。
        assert len(entries) == 2
        assert {e.v1_clause_ref for e in entries} == {"c1", "c2"}
        assert all(e.category == "unmatched" for e in entries)
        assert all(e.v2_clause_ref is None for e in entries)

    def test_both_clauses_present_in_both_versions_stay_separate(self):
        v1_results = [
            _rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c1"),
            _rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c2"),
        ]
        # V2 修复了 c1，c2 仍然违规
        v2_results = [
            _rule_result("probation_salary_below_80_percent", RiskLevel.NONE, clause_id="c1"),
            _rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c2"),
        ]
        entries = risk_diff(v1_results, v2_results)

        assert len(entries) == 2
        by_ref = {e.v1_clause_ref or e.v2_clause_ref: e for e in entries}
        assert by_ref["c1"].category == "resolved"
        assert by_ref["c2"].category == "unchanged"


class TestSameRuleSameClauseMatches:
    """2. V1/V2 都存在相同规则、相同条款的结果时，必须正确匹配为同一条。"""

    def test_matches_as_single_entry_when_risk_level_unchanged(self):
        v1_results = [_rule_result("probation_duration_exceeds_legal_cap", RiskLevel.HIGH, clause_id="c3")]
        v2_results = [_rule_result("probation_duration_exceeds_legal_cap", RiskLevel.HIGH, clause_id="c3")]
        entries = risk_diff(v1_results, v2_results)

        assert len(entries) == 1
        assert entries[0].category == "unchanged"
        assert entries[0].v1_clause_ref == "c3"
        assert entries[0].v2_clause_ref == "c3"

    def test_matches_as_single_entry_when_risk_resolved(self):
        v1_results = [_rule_result("probation_duration_exceeds_legal_cap", RiskLevel.HIGH, clause_id="c3")]
        v2_results = [_rule_result("probation_duration_exceeds_legal_cap", RiskLevel.NONE, clause_id="c3")]
        entries = risk_diff(v1_results, v2_results)

        assert len(entries) == 1
        assert entries[0].category == "resolved"


class TestRuleHitClauseChangesBetweenVersions:
    """3. 同一规则在 V1/V2 命中的条款发生变化时，不能静默丢失——必须分别
    体现为 V1 侧 unmatched 和 V2 侧 new，而不是互相覆盖、只剩一条甚至消失。
    """

    def test_clause_shift_produces_unmatched_and_new_not_a_silent_overwrite(self):
        v1_results = [_rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c1")]
        v2_results = [_rule_result("probation_salary_below_80_percent", RiskLevel.HIGH, clause_id="c5")]
        entries = risk_diff(v1_results, v2_results)

        # 旧实现：v1_by_key 和 v2_by_key 的 key 都是 ("rule", rule_id)，
        # 二者 key 相同会被当成"同一条匹配上了"，直接走 unchanged 分支，
        # 完全看不出 c1 这条风险在 V2 里其实已经不存在、c5 是全新出现的——
        # 这正是"静默丢失"的另一种表现形式（不是条目数变少，而是内容被错误合并）。
        assert len(entries) == 2
        categories = {e.category for e in entries}
        assert categories == {"unmatched", "new"}

        unmatched = next(e for e in entries if e.category == "unmatched")
        new = next(e for e in entries if e.category == "new")
        assert unmatched.v1_clause_ref == "c1"
        assert unmatched.v2_clause_ref is None
        assert new.v2_clause_ref == "c5"
        assert new.v1_clause_ref is None


class TestLlmMatchingUnaffected:
    """4. 原有 LLM 风险结果按 clause_id 匹配的行为不能被破坏。"""

    def test_llm_results_still_match_by_clause_id(self):
        v1_results = [_llm_result("c1", RiskLevel.HIGH)]
        v2_results = [_llm_result("c1", RiskLevel.NONE)]
        entries = risk_diff(v1_results, v2_results)

        assert len(entries) == 1
        assert entries[0].category == "resolved"
        assert entries[0].v1_clause_ref == "c1"
        assert entries[0].v2_clause_ref == "c1"

    def test_llm_results_with_different_clause_ids_are_unmatched_and_new(self):
        v1_results = [_llm_result("c1", RiskLevel.HIGH)]
        v2_results = [_llm_result("c2", RiskLevel.HIGH)]
        entries = risk_diff(v1_results, v2_results)

        assert len(entries) == 2
        assert {e.category for e in entries} == {"unmatched", "new"}


class TestCrossClauseRuleResultsWithoutClauseId:
    """5.（补充）clause_id 为 None、只有 related_clause_ids 的跨条款规则结果，
    不应该因为 clause_id 都是 None 就被当成同一条、互相覆盖。
    """

    def test_different_related_clause_ids_are_not_collapsed(self):
        v1_results = [
            _rule_result(
                "probation_duration_exceeds_legal_cap",
                RiskLevel.HIGH,
                clause_id=None,
                related_clause_ids=["c1", "c2"],
            )
        ]
        v2_results = [
            _rule_result(
                "probation_duration_exceeds_legal_cap",
                RiskLevel.HIGH,
                clause_id=None,
                related_clause_ids=["c9", "c10"],
            )
        ]
        entries = risk_diff(v1_results, v2_results)

        # related_clause_ids 完全不同，说明是不同的跨条款事实组合，不能匹配成同一条。
        assert len(entries) == 2
        assert {e.category for e in entries} == {"unmatched", "new"}

    def test_same_related_clause_ids_do_match(self):
        v1_results = [
            _rule_result(
                "probation_duration_exceeds_legal_cap",
                RiskLevel.HIGH,
                clause_id=None,
                related_clause_ids=["c1", "c2"],
            )
        ]
        v2_results = [
            _rule_result(
                "probation_duration_exceeds_legal_cap",
                RiskLevel.NONE,
                clause_id=None,
                related_clause_ids=["c1", "c2"],
            )
        ]
        entries = risk_diff(v1_results, v2_results)

        assert len(entries) == 1
        assert entries[0].category == "resolved"
