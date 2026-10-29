"""contract 模块的单元测试。运行：在项目根目录执行 `pytest`。"""

import hashlib
import json
import uuid

import pytest

from infra.storage import ContractError, ContractManager, ContractNotFoundError
from core import Contract, ContractStatus, ContractVersion
from config import settings

# 含中文、CRLF 的内容，确认文件是被原样保存的
DATA = "第一条 合同期限\r\n本合同期限三年。\r\n".encode("utf-8")


def make_file(tmp_path, name="合同.txt", data=DATA):
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    path = src_dir / name
    path.write_bytes(data)
    return path


def make_manager(tmp_path) -> ContractManager:
    return ContractManager(tmp_path / "contracts")


# ---------- 创建：contract_id ----------

def test_create_generates_uuid4_contract_id(tmp_path):
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path))
    parsed = uuid.UUID(contract.contract_id)
    assert parsed.version == 4
    assert parsed.hex == contract.contract_id  # 统一使用 32 位小写十六进制


def test_each_upload_gets_a_different_id(tmp_path):
    manager = make_manager(tmp_path)
    src = make_file(tmp_path)
    assert manager.create_contract(src).contract_id != manager.create_contract(src).contract_id


# ---------- 创建：文件保存 ----------

def test_original_file_is_saved_byte_for_byte(tmp_path):
    manager = make_manager(tmp_path)
    contract = manager.create_contract(make_file(tmp_path))
    saved = tmp_path / "contracts" / contract.contract_id / "original_file" / "合同.txt"
    assert saved.is_file()
    assert saved.read_bytes() == DATA  # CRLF 也原样保留


def test_source_file_is_copied_not_moved(tmp_path):
    src = make_file(tmp_path)
    make_manager(tmp_path).create_contract(src)
    assert src.read_bytes() == DATA


def test_contract_directory_contains_only_expected_entries(tmp_path):
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path))
    entries = {p.name for p in (tmp_path / "contracts" / contract.contract_id).iterdir()}
    assert entries == {"original_file", "metadata.json"}  # 没有遗留的 .tmp 文件


# ---------- 创建：metadata.json ----------

def test_metadata_json_is_written_and_matches_contract(tmp_path):
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path))
    metadata_path = tmp_path / "contracts" / contract.contract_id / "metadata.json"
    assert metadata_path.is_file()

    text = metadata_path.read_text(encoding="utf-8")
    assert json.loads(text)["contract_id"] == contract.contract_id
    assert "合同.txt" in text  # 中文没有被转义成 \uXXXX，便于人工查看
    assert Contract.model_validate_json(text) == contract


# ---------- 创建：sha256 及其他字段 ----------

def test_sha256_and_size_are_correct(tmp_path):
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path))
    assert contract.sha256 == hashlib.sha256(DATA).hexdigest()
    assert contract.size_bytes == len(DATA)


def test_sha256_handles_content_larger_than_one_chunk(tmp_path):
    big = b"a" * (1024 * 1024 * 2 + 123)  # 跨多个读取块
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path, "big.txt", big))
    assert contract.sha256 == hashlib.sha256(big).hexdigest()
    assert contract.size_bytes == len(big)


def test_contract_fields(tmp_path):
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path, "Contract.TXT"))
    assert contract.filename == "Contract.TXT"
    assert contract.file_format == "txt"  # 小写、不带点
    assert contract.status is ContractStatus.UPLOADED
    assert contract.error is None
    assert contract.created_at.tzinfo is not None


def test_same_file_uploaded_twice_gives_same_sha256_but_separate_contracts(tmp_path):
    manager = make_manager(tmp_path)
    src = make_file(tmp_path)
    a, b = manager.create_contract(src), manager.create_contract(src)
    assert a.sha256 == b.sha256
    assert a.contract_id != b.contract_id


# ---------- get_contract ----------

def test_get_contract_reads_back_created_contract(tmp_path):
    manager = make_manager(tmp_path)
    contract = manager.create_contract(make_file(tmp_path))
    assert manager.get_contract(contract.contract_id) == contract


def test_get_contract_works_from_a_new_manager_instance(tmp_path):
    contract = make_manager(tmp_path).create_contract(make_file(tmp_path))
    assert make_manager(tmp_path).get_contract(contract.contract_id) == contract  # 确实是从磁盘读的


def test_get_unknown_contract_raises_not_found(tmp_path):
    with pytest.raises(ContractNotFoundError):
        make_manager(tmp_path).get_contract(uuid.uuid4().hex)


def test_get_contract_rejects_malformed_ids(tmp_path):
    manager = make_manager(tmp_path)
    for bad in ("", "abc", "../secret", "..", "a" * 31, "A" * 32, str(uuid.uuid4())):
        with pytest.raises(ContractNotFoundError):
            manager.get_contract(bad)


def test_incomplete_directory_without_metadata_is_not_found(tmp_path):
    cid = uuid.uuid4().hex
    (tmp_path / "contracts" / cid).mkdir(parents=True)
    with pytest.raises(ContractNotFoundError):
        make_manager(tmp_path).get_contract(cid)


def test_corrupted_metadata_raises_contract_error(tmp_path):
    manager = make_manager(tmp_path)
    contract = manager.create_contract(make_file(tmp_path))
    (tmp_path / "contracts" / contract.contract_id / "metadata.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError):
        manager.get_contract(contract.contract_id)


# ---------- 输入校验与失败清理 ----------

def test_missing_file_and_directory_rejected(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(FileNotFoundError):
        manager.create_contract(tmp_path / "nope.txt")
    with pytest.raises(FileNotFoundError):
        manager.create_contract(tmp_path)  # 目录不是文件


def test_file_without_valid_extension_rejected_and_nothing_created(tmp_path):
    manager = make_manager(tmp_path)
    for name in ("contract", "a.t-x"):
        with pytest.raises(ContractError):
            manager.create_contract(make_file(tmp_path, name))
    assert not (tmp_path / "contracts").exists()  # 校验先于建目录，什么都没留下


def test_failure_during_creation_leaves_no_residue(tmp_path):
    class DiskFullManager(ContractManager):
        def save_original_file(self, contract_id, source_path):
            raise RuntimeError("磁盘已满")

    root = tmp_path / "contracts"
    with pytest.raises(RuntimeError):
        DiskFullManager(root).create_contract(make_file(tmp_path))
    assert list(root.iterdir()) == []


# ---------- save_original_file ----------

def test_save_original_file_refuses_to_overwrite(tmp_path):
    manager = make_manager(tmp_path)
    contract = manager.create_contract(make_file(tmp_path))
    other = make_file(tmp_path, "other.txt", b"tampered")
    with pytest.raises(ContractError):
        manager.save_original_file(contract.contract_id, other)
    saved = tmp_path / "contracts" / contract.contract_id / "original_file" / "合同.txt"
    assert saved.read_bytes() == DATA  # 原件没被动过


def test_save_original_file_for_unknown_contract_rejected(tmp_path):
    with pytest.raises(ContractNotFoundError):
        make_manager(tmp_path).save_original_file(uuid.uuid4().hex, make_file(tmp_path))


def test_save_original_file_returns_saved_path(tmp_path):
    manager = make_manager(tmp_path)
    cid = uuid.uuid4().hex
    (tmp_path / "contracts" / cid).mkdir(parents=True)
    saved = manager.save_original_file(cid, make_file(tmp_path))
    assert saved == tmp_path / "contracts" / cid / "original_file" / "合同.txt"
    assert saved.read_bytes() == DATA


# ---------- 默认根目录 ----------

def test_default_root_is_project_data_contracts():
    root = ContractManager().root_dir
    assert root.is_absolute()
    assert root.parts[-2:] == ("runtime", "contracts")
    assert root == settings.CONTRACTS_DIR  # 指向项目自带的目录，而不是随当前目录变化


# ---------- list_contracts：exclude_version_hosts（阶段 1 新增） ----------

def _make_version(contract_id: str, linked_contract_id: str, version_number: str = "v2") -> ContractVersion:
    return ContractVersion(
        version_id=f"{contract_id}_{version_number}",
        contract_id=contract_id,
        version_number=version_number,
        linked_contract_id=linked_contract_id,
    )


def test_list_contracts_default_behavior_is_unchanged(tmp_path):
    """不传参数时必须和改动前完全一样：哪怕存在版本记录，也不会过滤任何东西。"""
    manager = make_manager(tmp_path)
    a = manager.create_contract(make_file(tmp_path, "a.txt"))
    b = manager.create_contract(make_file(tmp_path, "b.txt"))
    manager.save_version(_make_version(a.contract_id, b.contract_id))

    contracts = manager.list_contracts()

    assert {c.contract_id for c in contracts} == {a.contract_id, b.contract_id}


def test_list_contracts_exclude_version_hosts_keeps_contract_without_versions(tmp_path):
    """没有任何版本记录的原始合同，打开过滤也必须继续出现在列表里。"""
    manager = make_manager(tmp_path)
    a = manager.create_contract(make_file(tmp_path, "a.txt"))

    contracts = manager.list_contracts(exclude_version_hosts=True)

    assert [c.contract_id for c in contracts] == [a.contract_id]


def test_list_contracts_exclude_version_hosts_removes_linked_contract(tmp_path):
    """被某条 ContractVersion.linked_contract_id 引用的合同必须被排除。"""
    manager = make_manager(tmp_path)
    a = manager.create_contract(make_file(tmp_path, "a.txt"))
    b = manager.create_contract(make_file(tmp_path, "b.txt"))
    manager.save_version(_make_version(a.contract_id, b.contract_id))

    contracts = manager.list_contracts(exclude_version_hosts=True)

    assert [c.contract_id for c in contracts] == [a.contract_id]


def test_list_contracts_exclude_version_hosts_dedupes_repeated_references(tmp_path):
    """同一个 linked_contract_id 被两条不同家族的版本记录引用时，依然只需要
    排除一次，不应该报错或产生重复/异常结果（集合天然去重）。
    """
    manager = make_manager(tmp_path)
    a1 = manager.create_contract(make_file(tmp_path, "a1.txt"))
    a2 = manager.create_contract(make_file(tmp_path, "a2.txt"))
    b = manager.create_contract(make_file(tmp_path, "b.txt"))
    manager.save_version(_make_version(a1.contract_id, b.contract_id))
    manager.save_version(_make_version(a2.contract_id, b.contract_id))

    contracts = manager.list_contracts(exclude_version_hosts=True)

    assert {c.contract_id for c in contracts} == {a1.contract_id, a2.contract_id}


def test_list_contracts_exclude_version_hosts_survives_corrupted_version_record(tmp_path):
    """某份合同自己的版本记录损坏时：
    - 不能让整个合同列表查询失败（不抛异常）；
    - 不能因此误删任何一份原始合同——包括版本记录本身损坏的那一份合同
      自己，以及其他完全不相关的合同。
    """
    manager = make_manager(tmp_path)
    a = manager.create_contract(make_file(tmp_path, "a.txt"))
    b = manager.create_contract(make_file(tmp_path, "b.txt"))

    versions_dir = tmp_path / "contracts" / a.contract_id / "versions"
    versions_dir.mkdir(parents=True)
    (versions_dir / "version_v2.json").write_text("{not valid json", encoding="utf-8")

    contracts = manager.list_contracts(exclude_version_hosts=True)

    assert {c.contract_id for c in contracts} == {a.contract_id, b.contract_id}


def test_list_contracts_exclude_version_hosts_does_not_touch_stored_data(tmp_path):
    """被排除出合同库列表，不代表这份合同的数据被动了——get_contract 之类
    的直接读取接口必须完全不受影响，文件也原样保留。
    """
    manager = make_manager(tmp_path)
    a = manager.create_contract(make_file(tmp_path, "a.txt"))
    b = manager.create_contract(make_file(tmp_path, "b.txt"))
    manager.save_version(_make_version(a.contract_id, b.contract_id))

    manager.list_contracts(exclude_version_hosts=True)  # 触发一次过滤

    fetched = manager.get_contract(b.contract_id)
    assert fetched.contract_id == b.contract_id
    assert (tmp_path / "contracts" / b.contract_id / "metadata.json").is_file()
