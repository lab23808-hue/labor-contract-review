"""review/schemas.py（LLMReviewOutput）的单元测试。"""

import pytest
from pydantic import ValidationError

from agents.review_schemas import LLMReviewOutput
from schemas import RiskLevel


def test_valid_risk_output():
    output = LLMReviewOutput(
        risk=True,
        risk_level=RiskLevel.HIGH,
        reason="试用期工资低于法定最低标准",
        legal_basis=["《劳动合同法》第二十条"],
        suggestion="调整试用期工资至不低于百分之八十",
    )
    assert output.risk is True
    assert output.risk_level == RiskLevel.HIGH


def test_valid_no_risk_output():
    output = LLMReviewOutput(risk=False, risk_level=RiskLevel.NONE, reason="符合法律规定")
    assert output.risk is False
    assert output.legal_basis == []
    assert output.suggestion == ""


def test_risk_true_with_none_level_rejected():
    with pytest.raises(ValidationError):
        LLMReviewOutput(risk=True, risk_level=RiskLevel.NONE, reason="矛盾的组合")


def test_risk_false_with_non_none_level_rejected():
    with pytest.raises(ValidationError):
        LLMReviewOutput(risk=False, risk_level=RiskLevel.LOW, reason="矛盾的组合")


def test_missing_reason_rejected():
    with pytest.raises(ValidationError):
        LLMReviewOutput(risk=False, risk_level=RiskLevel.NONE, reason="")


def test_can_parse_from_raw_json_string():
    raw = (
        '{"risk": true, "risk_level": "medium", "reason": "工作地点条款赋予单方调整权",'
        ' "legal_basis": ["《劳动合同法》第三十五条"], "suggestion": "改为协商一致后可调整"}'
    )
    output = LLMReviewOutput.model_validate_json(raw)
    assert output.risk_level == RiskLevel.MEDIUM
    assert output.legal_basis == ["《劳动合同法》第三十五条"]


def test_invalid_risk_level_string_rejected():
    with pytest.raises(ValidationError):
        LLMReviewOutput.model_validate_json(
            '{"risk": true, "risk_level": "严重", "reason": "x"}'
        )
