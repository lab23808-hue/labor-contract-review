"""schemas 的单元测试。运行：在项目根目录执行 `pytest`。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schemas import (
    RISK_LEVEL_LABELS_ZH,
    Clause,
    Contract,
    ContractStatus,
    Evidence,
    FailedClause,
    ReviewReport,
    ReviewResult,
    ReviewSource,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Clause
# ---------------------------------------------------------------------------

def make_clause(**overrides) -> Clause:
    data = dict(
        contract_id="contract_001",
        clause_id="clause_003",
        original_text="第三条 工作地点",
        start_char=0,
        end_char=8,
    )
    data.update(overrides)
    return Clause(**data)


def test_clause_defaults():
    c = make_clause()
    assert c.clause_type == "unknown"
    assert c.page_number is None
    assert c.parent_clause is None
    assert c.hierarchy_level == 0
    assert c.metadata == {}


def test_clause_requires_contract_id():
    with pytest.raises(ValidationError):
        Clause(clause_id="c", original_text="x", start_char=0, end_char=1)  # 缺 contract_id
    with pytest.raises(ValidationError):
        make_clause(contract_id="")


def test_clause_with_parent_and_level():
    c = make_clause(clause_id="clause_003_1", parent_clause="clause_003", hierarchy_level=1)
    assert c.parent_clause == "clause_003"
    assert c.hierarchy_level == 1


def test_clause_metadata_not_shared_between_instances():
    a, b = make_clause(), make_clause()
    a.metadata["k"] = "v"
    assert b.metadata == {}


def test_clause_end_before_start_rejected():
    with pytest.raises(ValidationError):
        make_clause(start_char=10, end_char=5)


def test_clause_empty_range_allowed():
    assert make_clause(start_char=5, end_char=5).end_char == 5


def test_clause_negative_offset_rejected():
    with pytest.raises(ValidationError):
        make_clause(start_char=-1)


def test_clause_empty_text_rejected():
    with pytest.raises(ValidationError):
        make_clause(original_text="")


def test_clause_page_number_must_be_positive():
    with pytest.raises(ValidationError):
        make_clause(page_number=0)


def test_clause_json_roundtrip():
    c = make_clause(page_number=2, metadata={"a": 1})
    assert Clause.model_validate_json(c.model_dump_json()) == c


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def test_evidence_minimal():
    e = Evidence(content="用人单位应当依法...", source="劳动合同法")
    assert e.article is None
    assert e.metadata == {}


def test_evidence_requires_content_and_source():
    with pytest.raises(ValidationError):
        Evidence(content="", source="劳动合同法")
    with pytest.raises(ValidationError):
        Evidence(content="x")  # 缺 source


# ---------------------------------------------------------------------------
# RiskLevel
# ---------------------------------------------------------------------------

def test_risk_level_severity_order():
    order = [RiskLevel.NONE, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
    assert [lv.severity for lv in order] == sorted(lv.severity for lv in order)
    assert len({lv.severity for lv in order}) == 4


def test_risk_level_chinese_labels():
    assert RISK_LEVEL_LABELS_ZH == {
        RiskLevel.NONE: "无",
        RiskLevel.LOW: "低",
        RiskLevel.MEDIUM: "中",
        RiskLevel.HIGH: "高",
    }


# ---------------------------------------------------------------------------
# ReviewResult
# ---------------------------------------------------------------------------

def llm_result(**overrides) -> ReviewResult:
    data = dict(clause_id="clause_003", risk=True, risk_level="high", reason="单方调岗", source="llm")
    data.update(overrides)
    return ReviewResult(**data)


def rule_result(**overrides) -> ReviewResult:
    data = dict(risk=True, risk_level="medium", reason="缺少社保条款", source="rule", rule_id="R001")
    data.update(overrides)
    return ReviewResult(**data)


def test_llm_result_basic_and_zh_label():
    r = llm_result()
    assert r.risk_level is RiskLevel.HIGH
    assert r.source is ReviewSource.LLM
    assert r.risk_level_zh == "高"
    assert r.legal_basis == []
    assert r.related_clause_ids == []
    assert r.suggestion == ""
    assert r.rule_id is None


def test_every_level_maps_to_chinese():
    for level in RiskLevel:
        r = llm_result(risk=level != RiskLevel.NONE, risk_level=level.value)
        assert r.risk_level_zh == RISK_LEVEL_LABELS_ZH[level]


def test_none_level_means_no_risk():
    r = llm_result(risk=False, risk_level="none", reason="合规")
    assert r.risk is False
    assert r.risk_level_zh == "无"


def test_risk_and_level_must_agree():
    with pytest.raises(ValidationError):
        llm_result(risk=True, risk_level="none")
    for level in ("low", "medium", "high"):
        with pytest.raises(ValidationError):
            llm_result(risk=False, risk_level=level)


def test_llm_result_requires_clause_id_and_no_rule_id():
    with pytest.raises(ValidationError):
        llm_result(clause_id=None)
    with pytest.raises(ValidationError):
        llm_result(rule_id="R001")


def test_rule_result_requires_rule_id():
    with pytest.raises(ValidationError):
        rule_result(rule_id=None)


def test_rule_result_may_have_no_clause_for_missing_clause_problems():
    r = rule_result()
    assert r.clause_id is None
    assert r.source is ReviewSource.RULE


def test_rule_result_can_reference_related_clauses():
    r = rule_result(related_clause_ids=["clause_001", "clause_005"], rule_id="R002")
    assert r.related_clause_ids == ["clause_001", "clause_005"]


def test_result_rejects_chinese_or_unknown_level_and_source():
    with pytest.raises(ValidationError):
        llm_result(risk_level="高")  # 内部只接受英文
    with pytest.raises(ValidationError):
        llm_result(source="human")


def test_result_serializes_enums_as_plain_strings_and_roundtrips():
    r = llm_result(legal_basis=["《劳动合同法》第十七条"])
    dumped = r.model_dump(mode="json")
    assert dumped["risk_level"] == "high"
    assert dumped["source"] == "llm"
    assert ReviewResult.model_validate_json(r.model_dump_json()) == r


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

SHA = "a" * 64


def make_contract(**overrides) -> Contract:
    data = dict(contract_id="c1", filename="合同.txt", file_format="txt", sha256=SHA, size_bytes=123)
    data.update(overrides)
    return Contract(**data)


def test_contract_defaults():
    c = make_contract()
    assert c.status is ContractStatus.UPLOADED
    assert c.error is None
    assert c.metadata == {}
    assert c.created_at.tzinfo is not None
    assert c.updated_at.tzinfo is not None


def test_contract_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        make_contract(created_at=datetime(2026, 1, 1))


def test_contract_aware_datetime_accepted():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert make_contract(created_at=ts).created_at == ts


def test_contract_sha256_must_be_64_lowercase_hex():
    for bad in ("abc", "A" * 64, "g" * 64, "a" * 63):
        with pytest.raises(ValidationError):
            make_contract(sha256=bad)


def test_contract_file_format_must_be_lowercase_without_dot():
    for bad in (".txt", "TXT", ""):
        with pytest.raises(ValidationError):
            make_contract(file_format=bad)


def test_contract_size_cannot_be_negative():
    with pytest.raises(ValidationError):
        make_contract(size_bytes=-1)


def test_contract_failed_status_requires_error():
    with pytest.raises(ValidationError):
        make_contract(status="failed")
    assert make_contract(status="failed", error="解码失败").status is ContractStatus.FAILED


def test_contract_json_roundtrip():
    c = make_contract(status="parsed", metadata={"encoding": "utf-8-sig"})
    assert Contract.model_validate_json(c.model_dump_json()) == c


# ---------------------------------------------------------------------------
# ReviewReport
# ---------------------------------------------------------------------------

def test_empty_report():
    r = ReviewReport(contract_id="c1")
    assert r.overall_risk_level is RiskLevel.NONE
    assert r.summary.model_dump() == {"high": 0, "medium": 0, "low": 0, "none": 0}
    assert r.failed_clauses == []
    assert r.generated_at.tzinfo is not None
    assert r.versions.llm_model is None


def test_report_summary_and_overall_level():
    results = [
        llm_result(clause_id="clause_001", risk=False, risk_level="none", reason="合规"),
        llm_result(clause_id="clause_002", risk=True, risk_level="low"),
        llm_result(clause_id="clause_003", risk=True, risk_level="high"),
        rule_result(risk_level="medium"),
        rule_result(rule_id="R002", risk_level="medium"),
    ]
    r = ReviewReport(contract_id="c1", results=results)
    assert r.overall_risk_level is RiskLevel.HIGH
    assert r.summary.model_dump() == {"high": 1, "medium": 2, "low": 1, "none": 1}


def test_report_overall_level_without_high():
    r = ReviewReport(contract_id="c1", results=[rule_result(risk_level="medium"), llm_result(risk_level="low")])
    assert r.overall_risk_level is RiskLevel.MEDIUM


def test_report_records_failed_clauses():
    r = ReviewReport(contract_id="c1", failed_clauses=[FailedClause(clause_id="clause_007", error="LLM 超时")])
    assert r.failed_clauses[0].clause_id == "clause_007"


def test_report_json_contains_computed_fields_and_roundtrips():
    r = ReviewReport(contract_id="c1", results=[llm_result()])
    dumped = r.model_dump(mode="json")
    assert dumped["overall_risk_level"] == "high"
    assert dumped["summary"]["high"] == 1
    assert dumped["results"][0]["source"] == "llm"
    # 从 JSON 读回时，计算字段被忽略并重新计算
    assert ReviewReport.model_validate_json(r.model_dump_json()) == r


def test_report_naive_generated_at_rejected():
    with pytest.raises(ValidationError):
        ReviewReport(contract_id="c1", generated_at=datetime(2026, 1, 1))


def test_report_lists_not_shared_between_instances():
    a, b = ReviewReport(contract_id="c1"), ReviewReport(contract_id="c2")
    a.results.append(llm_result())
    assert b.results == []
