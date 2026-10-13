"""evaluation/generate_contracts.py 的单元测试：不依赖磁盘上已经生成的文件
（和 test_eval_schemas.py 里"校验已生成文件"的测试互补），直接调用生成器
函数验证拼装逻辑本身的正确性。
"""

from evaluation import clause_bank as cb
from evaluation.generate_contracts import build_all_contracts_with_parts, build_contract
from evaluation.schemas import ContractSampleType


def test_build_contract_produces_consistent_boundaries_and_text():
    parts = [cb.wage_payment_compliant(), cb.probation_salary(50)]
    contract = build_contract(
        sample_id="unit_test_01",
        sample_type=ContractSampleType.CLEAR_RISK,
        source="newly_designed",
        description="unit test",
        parts=parts,
    )
    assert len(contract.clauses) == 2
    for clause in contract.clauses:
        assert contract.full_text[clause.start_char : clause.end_char] == clause.original_text
    # 第二条应该被判定为风险（50% < 80%）
    assert contract.clauses[1].risk is True
    assert contract.clauses[0].risk is False


def test_build_all_contracts_with_parts_returns_fifty_unique_samples():
    pairs = build_all_contracts_with_parts()
    assert len(pairs) == 50
    ids = [c.sample_id for c, _ in pairs]
    assert len(set(ids)) == 50


def test_build_all_contracts_with_parts_matches_required_distribution():
    pairs = build_all_contracts_with_parts()
    counts: dict = {}
    for contract, _ in pairs:
        counts[contract.sample_type] = counts.get(contract.sample_type, 0) + 1
    assert counts[ContractSampleType.CLEAR_RISK] == 20
    assert counts[ContractSampleType.BASICALLY_COMPLIANT] == 10
    assert counts[ContractSampleType.MIXED] == 10
    assert counts[ContractSampleType.BOUNDARY_COMPLEX] == 10


def test_parts_rule_expectation_count_matches_clause_count():
    """每份合同的 parts（条款原型）数量必须和最终 ContractAnswer 里的条款数量
    一一对应——这是 _rule_expectations_for() 用 zip() 配对的前提，如果两边
    数量不一致，zip() 会静默截断，诊断实验 6 就会悄悄漏掉条款而不报错。
    """
    for contract, parts in build_all_contracts_with_parts():
        assert len(parts) == len(contract.clauses), (
            f"{contract.sample_id}: parts 数量 {len(parts)} 和 clauses 数量 "
            f"{len(contract.clauses)} 不一致"
        )


def test_probation_salary_archetype_boundary_values():
    assert cb.probation_salary(79)["answer"]["risk"] is True
    assert cb.probation_salary(80)["answer"]["risk"] is False
    assert cb.probation_salary(81)["answer"]["risk"] is False


def test_contract_term_and_probation_boundary_values():
    # fixed_1y -> 法定上限 2 个月
    assert cb.contract_term_and_probation("fixed_1y", 2)["answer"]["risk"] is False
    assert cb.contract_term_and_probation("fixed_1y", 3)["answer"]["risk"] is True


def test_noncompete_requires_both_conditions_to_be_compliant():
    assert cb.noncompete(2, True)["answer"]["risk"] is False
    assert cb.noncompete(3, True)["answer"]["risk"] is True  # 超 2 年
    assert cb.noncompete(2, False)["answer"]["risk"] is True  # 无补偿
