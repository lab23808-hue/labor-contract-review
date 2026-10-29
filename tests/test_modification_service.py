import pytest

from app.v2_generation_service import V2GenerationService
from infra.storage import ContractManager
from core import (
    Clause,
    ModificationBatchStatus,
    ModificationResult,
    ModificationTaskStatus,
    ReviewReport,
    ReviewResult,
    ReviewSource,
    RiskLevel,
)
from domain.document.splitter import ClauseSplitter
from domain.modification.service import (
    ModificationConflictError,
    ModificationService,
    ModificationServiceError,
)


class FakeAgent:
    def __init__(self):
        self.calls = 0

    def generate_candidate(self, clause, review_result, lawyer_instructions):
        self.calls += 1
        return ModificationResult(
            clause_id=clause.clause_id,
            modified_text=clause.original_text + "\n（按律师意见修改）",
            reason="测试修改",
            legal_basis=[],
        )


class FakeReviewer:
    def review(self, clause):
        return ReviewResult(
            clause_id=clause.clause_id,
            risk=False,
            risk_level=RiskLevel.NONE,
            reason="修改后审查：无风险",
            legal_basis=[],
            source=ReviewSource.LLM,
        )


@pytest.fixture
def setup(tmp_path):
    manager = ContractManager(root_dir=tmp_path / "contracts")
    text = "第一条 工作内容\n乙方同意从事甲方安排的工作。\n\n第二条 工作地点\n乙方工作地点为深圳市。"
    source = tmp_path / "contract.txt"
    source.write_text(text, encoding="utf-8")
    contract = manager.create_contract(source)
    manager.save_parsed_text(contract.contract_id, text)
    clauses = ClauseSplitter().split(text, contract.contract_id)
    manager.save_clauses(contract.contract_id, clauses)
    result = ReviewResult(
        clause_id=clauses[0].clause_id,
        risk=True,
        risk_level=RiskLevel.HIGH,
        reason="测试风险",
        legal_basis=["《劳动合同法》第十七条"],
        source=ReviewSource.LLM,
    )
    record = manager.save_review(
        contract.contract_id,
        ReviewReport(contract_id=contract.contract_id, results=[result]),
    )
    service = ModificationService(manager, FakeAgent(), FakeReviewer())
    batch = service.create_batch(contract.contract_id, record.review_id)
    task = service.create_task(
        contract.contract_id, batch.batch_id, clauses[0].clause_id, "修改工作内容"
    )
    return manager, service, contract, batch, task


def test_create_start_confirm_and_batch_ready(setup):
    manager, service, contract, batch, task = setup

    started = service.start_modification(contract.contract_id, task.task_id)
    assert started.status == ModificationTaskStatus.WAITING_CONFIRMATION
    assert service.agent.calls == 1
    assert started.modification_attempts[0].risk_resolution.value == "resolved"

    confirmed = service.confirm(contract.contract_id, task.task_id)
    assert confirmed.status == ModificationTaskStatus.CONFIRMED
    assert manager.get_batch(contract.contract_id, batch.batch_id).status == ModificationBatchStatus.READY_FOR_V2


def test_reject_then_retry_and_confirm(setup):
    manager, service, contract, batch, task = setup
    service.start_modification(contract.contract_id, task.task_id)

    rejected = service.reject(contract.contract_id, task.task_id, "再改具体一点")
    assert rejected.status == ModificationTaskStatus.REJECTED
    assert len(rejected.lawyer_instructions) == 2

    service.start_modification(contract.contract_id, task.task_id)
    confirmed = service.confirm(contract.contract_id, task.task_id)
    assert confirmed.status == ModificationTaskStatus.CONFIRMED


def test_max_attempts_then_needs_human_and_abandon(setup):
    manager, service, contract, batch, task = setup

    for _ in range(3):
        service.start_modification(contract.contract_id, task.task_id)
        task = service.reject(contract.contract_id, task.task_id, "继续改")

    assert task.status == ModificationTaskStatus.NEEDS_HUMAN
    assert task.attempts_exhausted is True

    abandoned = service.abandon(contract.contract_id, task.task_id)
    assert abandoned.status == ModificationTaskStatus.ABANDONED


def test_conflict_for_same_clause_in_pending_task(setup):
    manager, service, contract, batch, task = setup
    with pytest.raises(ModificationConflictError):
        service.create_task(contract.contract_id, batch.batch_id, task.target_clause_id, "重复任务")


def test_v2_generation_success_and_repeat_rejected(setup):
    manager, service, contract, batch, task = setup
    service.start_modification(contract.contract_id, task.task_id)
    service.confirm(contract.contract_id, task.task_id)

    v2 = V2GenerationService(manager)
    version = v2.generate(contract.contract_id, batch.batch_id)
    assert version.version_number == "v2"
    assert manager.get_batch(contract.contract_id, batch.batch_id).status == ModificationBatchStatus.V2_GENERATED
    assert manager.get_modification_task(contract.contract_id, task.task_id).status == ModificationTaskStatus.CONFIRMED

    with pytest.raises(ModificationServiceError):
        v2.generate(contract.contract_id, batch.batch_id)


def test_v2_generation_failure_then_retry(setup, monkeypatch):
    manager, service, contract, batch, task = setup
    service.start_modification(contract.contract_id, task.task_id)
    service.confirm(contract.contract_id, task.task_id)

    import app.v2_generation_service as module

    original = module.parse_and_split_contract
    monkeypatch.setattr(module, "parse_and_split_contract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("解析失败")))
    v2 = V2GenerationService(manager)
    with pytest.raises(ModificationServiceError):
        v2.generate(contract.contract_id, batch.batch_id)
    assert manager.get_batch(contract.contract_id, batch.batch_id).status == ModificationBatchStatus.V2_FAILED

    monkeypatch.setattr(module, "parse_and_split_contract", original)
    version = v2.generate(contract.contract_id, batch.batch_id)
    assert version.version_number == "v2"
