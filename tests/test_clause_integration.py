"""contract + clause 整合测试：验证“解析结果 → 切分 → 保存 Clause”的数据流。

运行：在项目根目录执行 `pytest`。
"""

import uuid

import pytest

from infra.storage import ContractError, ContractManager, ContractNotFoundError
from core import ContractStatus
from domain.document.preparation import parse_contract, split_contract

CONTRACT_A = (
    "劳动合同书\n\n甲方：某某公司\n乙方：张三\n\n"
    "第一条 合同期限\n本合同自2024年1月1日起至2026年12月31日止。\n\n"
    "第二条 工作地点\n1.乙方工作地点为北京市。\n2.甲方可以根据经营需要调整工作地点。\n"
)
CONTRACT_B = "第一条 保密义务\n乙方应当对商业秘密保密。\n"


def make_manager(tmp_path) -> ContractManager:
    return ContractManager(tmp_path / "contracts")


def upload_and_parse(tmp_path, manager, text, name="合同.txt"):
    """走完整数据流的前半段：上传 → 解析，返回 (contract, parsed_text)。"""
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    src = src_dir / name
    src.write_bytes(text.encode("utf-8"))
    contract = manager.create_contract(src)
    parsed_text = parse_contract(contract.contract_id, manager)
    return contract, parsed_text


# ---------- 端到端：parsed_text 传入 ClauseSplitter，生成结构化 Clause ----------

def test_split_contract_produces_expected_clause_structure(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)

    clauses = split_contract(contract.contract_id, manager)

    assert [c.clause_id for c in clauses] == [
        "clause_000", "clause_001", "clause_002", "clause_002_1", "clause_002_2",
    ]


# ---------- 原文定位不丢失 ----------

def test_offsets_still_locate_correctly_into_parsed_text(tmp_path):
    manager = make_manager(tmp_path)
    contract, parsed_text = upload_and_parse(tmp_path, manager, CONTRACT_A)

    clauses = split_contract(contract.contract_id, manager)

    for c in clauses:
        assert parsed_text[c.start_char : c.end_char] == c.original_text


def test_offsets_still_valid_after_reading_clauses_back_from_disk(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)
    split_contract(contract.contract_id, manager)

    parsed_text = manager.get_parsed_text(contract.contract_id)
    clauses = manager.get_clauses(contract.contract_id)

    assert len(clauses) == 5
    for c in clauses:
        assert parsed_text[c.start_char : c.end_char] == c.original_text


# ---------- Clause 与合同 ID 绑定 ----------

def test_every_clause_is_bound_to_its_contract_id(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)

    clauses = split_contract(contract.contract_id, manager)

    assert clauses  # 确认列表非空，下面的检查才有意义
    assert {c.contract_id for c in clauses} == {contract.contract_id}


def test_save_clauses_rejects_mismatched_contract_id(tmp_path):
    # 直接调用 ContractManager 的保存接口，模拟调用方传错了别的合同的 Clause 列表
    from core import Clause

    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)

    wrong_clause = Clause(
        contract_id="别的合同的id", clause_id="clause_001", original_text="x", start_char=0, end_char=1
    )
    with pytest.raises(ContractError):
        manager.save_clauses(contract.contract_id, [wrong_clause])


# ---------- 保存结果可读回，且状态正确推进 ----------

def test_clauses_saved_to_disk_and_readable_back(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)

    clauses = split_contract(contract.contract_id, manager)

    saved_path = tmp_path / "contracts" / contract.contract_id / "clauses.json"
    assert saved_path.is_file()
    assert manager.get_clauses(contract.contract_id) == clauses


def test_contract_status_updated_to_split(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)
    assert manager.get_contract(contract.contract_id).status is ContractStatus.PARSED

    split_contract(contract.contract_id, manager)

    reloaded = manager.get_contract(contract.contract_id)
    assert reloaded.status is ContractStatus.SPLIT
    assert reloaded.sha256 == contract.sha256  # 其余字段不受影响


def test_resplitting_overwrites_previous_result(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)

    first = split_contract(contract.contract_id, manager)
    second = split_contract(contract.contract_id, manager)  # 第二次不应报错

    assert first == second


# ---------- 多合同之间数据隔离 ----------

def test_multiple_contracts_clauses_are_isolated(tmp_path):
    manager = make_manager(tmp_path)
    contract_a, _ = upload_and_parse(tmp_path, manager, CONTRACT_A, name="a.txt")
    contract_b, _ = upload_and_parse(tmp_path, manager, CONTRACT_B, name="b.txt")

    clauses_a = split_contract(contract_a.contract_id, manager)
    clauses_b = split_contract(contract_b.contract_id, manager)

    # 两份合同都从 clause_001 开始编号，clause_id 会重复，
    # 但各自的 contract_id 不同，不会互相覆盖或串数据。
    assert [c.clause_id for c in clauses_b] == ["clause_001"]
    assert clauses_b[0].contract_id == contract_b.contract_id
    assert clauses_b[0].original_text == "第一条 保密义务\n乙方应当对商业秘密保密。"

    assert {c.contract_id for c in clauses_a} == {contract_a.contract_id}
    assert {c.contract_id for c in clauses_b} == {contract_b.contract_id}

    # 分别读回，互不影响
    assert manager.get_clauses(contract_a.contract_id) == clauses_a
    assert manager.get_clauses(contract_b.contract_id) == clauses_b


def test_contract_directories_do_not_leak_into_each_other(tmp_path):
    manager = make_manager(tmp_path)
    contract_a, _ = upload_and_parse(tmp_path, manager, CONTRACT_A, name="a.txt")
    contract_b, _ = upload_and_parse(tmp_path, manager, CONTRACT_B, name="b.txt")
    split_contract(contract_a.contract_id, manager)
    split_contract(contract_b.contract_id, manager)

    root = tmp_path / "contracts"
    assert (root / contract_a.contract_id / "clauses.json").is_file()
    assert (root / contract_b.contract_id / "clauses.json").is_file()
    assert contract_a.contract_id != contract_b.contract_id


# ---------- 边界情况 ----------

def test_splitting_before_parsing_raises(tmp_path):
    manager = make_manager(tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src = src_dir / "a.txt"
    src.write_text(CONTRACT_A, encoding="utf-8")
    contract = manager.create_contract(src)  # 只上传，没有解析

    with pytest.raises(ContractNotFoundError):
        split_contract(contract.contract_id, manager)


def test_splitting_unknown_contract_raises(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(ContractNotFoundError):
        split_contract(uuid.uuid4().hex, manager)


def test_get_clauses_before_splitting_raises(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)
    with pytest.raises(ContractNotFoundError):
        manager.get_clauses(contract.contract_id)


def test_corrupted_clauses_file_raises_contract_error(tmp_path):
    manager = make_manager(tmp_path)
    contract, _ = upload_and_parse(tmp_path, manager, CONTRACT_A)
    split_contract(contract.contract_id, manager)

    (tmp_path / "contracts" / contract.contract_id / "clauses.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ContractError):
        manager.get_clauses(contract.contract_id)
