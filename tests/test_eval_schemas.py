"""evaluation/schemas.py 的单元测试 + 对 50 份已生成评估样本的 schema 校验。

这是"验证评估集和标准答案格式"这件事本身的自动化测试（任务要求第七阶段
明确要求提供这类命令）。纯 pydantic + 标准库，不依赖任何未安装的第三方包，
可以在任何环境下运行。
"""

import json
from pathlib import Path

import pytest

from evaluation.schemas import ClauseAnswer, ContractAnswer, ContractSampleType, VerificationStatus

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "eval_samples"


def _make_minimal_clause(**overrides) -> dict:
    base = dict(
        clause_id="c00",
        order=0,
        start_char=0,
        end_char=10,
        original_text="第一条 内容",
        clause_type="测试",
        risk=False,
        reasoning="没有风险",
        legal_basis=[],
        legal_basis_verified_in_sources=False,
        annotated_by="tester",
        verification_status=VerificationStatus.CANDIDATE,
        annotation_basis="unit test",
    )
    base.update(overrides)
    return base


def test_clause_answer_rejects_risk_type_when_not_risky():
    with pytest.raises(ValueError):
        ClauseAnswer(**_make_minimal_clause(risk=False, risk_type="不应该有类型"))


def test_clause_answer_rejects_risk_without_basis_or_pending_note():
    with pytest.raises(ValueError):
        ClauseAnswer(**_make_minimal_clause(risk=True, legal_basis=[], pending_review_note=None))


def test_clause_answer_allows_risk_with_pending_review_note_and_no_basis():
    clause = ClauseAnswer(
        **_make_minimal_clause(risk=True, legal_basis=[], pending_review_note="证据不足，需要人工复核")
    )
    assert clause.risk is True


def test_clause_answer_rejects_unverified_basis_marked_as_candidate():
    with pytest.raises(ValueError):
        ClauseAnswer(
            **_make_minimal_clause(
                risk=True,
                legal_basis=["《劳动合同法》第二十条"],
                legal_basis_verified_in_sources=False,
                verification_status=VerificationStatus.CANDIDATE,
            )
        )


def test_clause_answer_allows_unverified_basis_when_marked_pending_review():
    clause = ClauseAnswer(
        **_make_minimal_clause(
            risk=True,
            legal_basis=["《劳动合同法》第二十条"],
            legal_basis_verified_in_sources=False,
            verification_status=VerificationStatus.PENDING_REVIEW,
        )
    )
    assert clause.verification_status == VerificationStatus.PENDING_REVIEW


def test_contract_answer_rejects_order_gap():
    clause0 = ClauseAnswer(**_make_minimal_clause(clause_id="c00", order=0, start_char=0, end_char=5, original_text="12345"))
    clause2 = ClauseAnswer(**_make_minimal_clause(clause_id="c01", order=2, start_char=5, end_char=10, original_text="67890"))
    with pytest.raises(ValueError):
        ContractAnswer(
            sample_id="s1",
            sample_type=ContractSampleType.CLEAR_RISK,
            source="newly_designed",
            description="test",
            full_text="1234567890",
            clauses=[clause0, clause2],
        )


def test_contract_answer_rejects_text_mismatch_with_boundaries():
    clause0 = ClauseAnswer(**_make_minimal_clause(clause_id="c00", order=0, start_char=0, end_char=5, original_text="WRONG"))
    with pytest.raises(ValueError):
        ContractAnswer(
            sample_id="s1",
            sample_type=ContractSampleType.CLEAR_RISK,
            source="newly_designed",
            description="test",
            full_text="1234567890",
            clauses=[clause0],
        )


def test_contract_answer_rejects_duplicate_clause_id():
    c0 = ClauseAnswer(**_make_minimal_clause(clause_id="dup", order=0, start_char=0, end_char=5, original_text="12345"))
    c1 = ClauseAnswer(**_make_minimal_clause(clause_id="dup", order=1, start_char=5, end_char=10, original_text="67890"))
    with pytest.raises(ValueError):
        ContractAnswer(
            sample_id="s1",
            sample_type=ContractSampleType.CLEAR_RISK,
            source="newly_designed",
            description="test",
            full_text="1234567890",
            clauses=[c0, c1],
        )


# ---------------------------------------------------------------------------
# 对 50 份已生成样本的真实校验（需要先跑过
# evaluation.generate_contracts.write_all()；如果 data/eval_samples 还没生成，
# 这些测试会被跳过而不是报错，便于单独跑 clause_bank/schemas 的单元测试）
# ---------------------------------------------------------------------------

def _load_generated_answers() -> list[dict]:
    answers_dir = DATA_DIR / "answers"
    if not answers_dir.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(answers_dir.glob("*.json"))]


def test_fifty_contracts_were_generated():
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    assert len(answers) == 50


def test_all_generated_answers_pass_schema_validation():
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    for raw in answers:
        ContractAnswer.model_validate(raw)  # 不抛异常即通过


def test_generated_distribution_matches_required_20_10_10_10():
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    counts: dict = {}
    for raw in answers:
        counts[raw["sample_type"]] = counts.get(raw["sample_type"], 0) + 1
    assert counts == {
        "clear_risk": 20,
        "basically_compliant": 10,
        "mixed": 10,
        "boundary_complex": 10,
    }


def test_every_contract_has_non_risk_clause_answers():
    """必须保留正常条款的标准答案，不能只标记风险条款——每份合同（包括全是
    风险条款主导的 clear_risk 类）都应该同时有若干正常条款的标准答案，
    否则就无法用这份样本计算误报率。
    """
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    for raw in answers:
        compliant_count = sum(1 for c in raw["clauses"] if not c["risk"])
        assert compliant_count > 0, f"{raw['sample_id']} 缺少正常条款标准答案"


def test_clear_risk_and_mixed_contracts_have_at_least_one_risk_clause():
    """clear_risk（明确存在风险）和 mixed（同时包含风险和合规条款）这两类
    按设计意图必须至少有一条风险条款；basically_compliant 和
    boundary_complex 允许全部是合规边界值（任务要求允许覆盖"合法约定、
    条件性规定"），不强制要求含风险条款。
    """
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    for raw in answers:
        if raw["sample_type"] not in ("clear_risk", "mixed"):
            continue
        risk_count = sum(1 for c in raw["clauses"] if c["risk"])
        assert risk_count > 0, f"{raw['sample_id']} 应该至少有一条风险条款，但没有"


def test_candidate_answers_never_claim_verified_status():
    """本次没有独立法律复核人员参与标注，所有标准答案的核验状态只能是
    candidate 或 pending_review，不应该出现任何"verified"（见
    evaluation/schemas.py::VerificationStatus 的 docstring 说明）。
    """
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    allowed = {"candidate", "pending_review"}
    for raw in answers:
        for clause in raw["clauses"]:
            assert clause["verification_status"] in allowed


def test_pending_review_samples_are_identifiable_for_exclusion_from_strict_accuracy():
    answers = _load_generated_answers()
    if not answers:
        pytest.skip("data/eval_samples/answers 不存在，先运行 scripts/generate_eval_contracts.py")
    pending = [
        (raw["sample_id"], c["clause_id"])
        for raw in answers
        for c in raw["clauses"]
        if c["verification_status"] == "pending_review"
    ]
    # 至少应该有一些 pending_review 样本（本次设计里刻意包含了信息不足/
    # 争议性场景），不是说数量必须精确等于某个值，只是确认"这个机制真的被用到了"。
    assert len(pending) > 0
