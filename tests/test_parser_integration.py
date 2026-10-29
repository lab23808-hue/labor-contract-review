"""contract + parser 整合测试：验证“上传 → 解析 → 保存解析结果”的数据流。

运行：在项目根目录执行 `pytest`。
"""

import uuid

import pytest

from infra.storage import ContractError, ContractManager, ContractNotFoundError
from core import ContractStatus
from domain.document.preparation import parse_contract

# 含中文、CRLF、首尾空白，用来验证内容是否被原样解析和保存
TEXT = "  \r\n第一条 工作地点\r\n1.北京市。\r\n2.可调整。\r\n  "


def make_manager(tmp_path) -> ContractManager:
    return ContractManager(tmp_path / "contracts")


def make_and_upload(tmp_path, manager, name="合同.txt", data=None):
    data = TEXT.encode("utf-8") if data is None else data
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    src = src_dir / name
    src.write_bytes(data)
    return manager.create_contract(src)


# ---------- 端到端：contract 创建后 parser 可以读取 ----------

def test_parser_can_read_contract_created_by_manager(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)

    text = parse_contract(contract.contract_id, manager)

    assert text == TEXT


# ---------- txt 内容解析正确 ----------

def test_txt_content_parsed_exactly(tmp_path):
    # 带 BOM，验证编码识别和“不改内容”（BOM 本身应被去掉，其余字节不变）
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager, data=b"\xef\xbb\xbf" + TEXT.encode("utf-8"))

    text = parse_contract(contract.contract_id, manager)

    assert text == TEXT
    assert "\ufeff" not in text


def test_gbk_encoded_txt_parsed_correctly(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager, data=TEXT.encode("gbk"))

    assert parse_contract(contract.contract_id, manager) == TEXT


# ---------- 解析结果保存正确 ----------

def test_parsed_text_is_saved_to_disk(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)

    parse_contract(contract.contract_id, manager)

    saved_path = tmp_path / "contracts" / contract.contract_id / "parsed_text.txt"
    assert saved_path.is_file()
    # newline="" 读取，确认落盘内容与解析结果逐字节一致（CRLF、首尾空白都不能变）
    with saved_path.open(encoding="utf-8", newline="") as f:
        assert f.read() == TEXT


def test_get_parsed_text_reads_back_saved_result(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)

    parse_contract(contract.contract_id, manager)

    assert manager.get_parsed_text(contract.contract_id) == TEXT


def test_contract_status_updated_to_parsed(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)
    assert contract.status is ContractStatus.UPLOADED

    parse_contract(contract.contract_id, manager)

    reloaded = manager.get_contract(contract.contract_id)
    assert reloaded.status is ContractStatus.PARSED
    assert reloaded.updated_at >= contract.updated_at
    # 除状态和更新时间外，其余字段（含 sha256）应保持不变
    assert reloaded.contract_id == contract.contract_id
    assert reloaded.sha256 == contract.sha256


def test_reparsing_overwrites_previous_result(tmp_path):
    # parsed_text.txt 是可重新生成的派生数据，允许覆盖（不同于原始文件）
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)

    parse_contract(contract.contract_id, manager)
    saved_path = tmp_path / "contracts" / contract.contract_id / "parsed_text.txt"
    assert saved_path.exists()

    parse_contract(contract.contract_id, manager)  # 第二次解析不应报错
    assert manager.get_parsed_text(contract.contract_id) == TEXT


# ---------- contract_id 对应正确（多份合同互不影响）----------

def test_multiple_contracts_are_isolated(tmp_path):
    manager = make_manager(tmp_path)
    a = make_and_upload(tmp_path, manager, name="a.txt", data="第一条 甲".encode("utf-8"))
    b = make_and_upload(tmp_path, manager, name="b.txt", data="第一条 乙".encode("utf-8"))

    text_a = parse_contract(a.contract_id, manager)
    text_b = parse_contract(b.contract_id, manager)

    assert text_a == "第一条 甲"
    assert text_b == "第一条 乙"
    assert manager.get_parsed_text(a.contract_id) == "第一条 甲"
    assert manager.get_parsed_text(b.contract_id) == "第一条 乙"


# ---------- 边界情况 ----------

def test_parsing_unknown_contract_raises(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(ContractNotFoundError):
        parse_contract(uuid.uuid4().hex, manager)


def test_get_parsed_text_before_parsing_raises(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)
    with pytest.raises(ContractNotFoundError):
        manager.get_parsed_text(contract.contract_id)


def test_parsing_empty_file_raises_and_does_not_change_status(tmp_path):
    # 内容全是空白：DocumentParser 会拒绝，不应产生 parsed_text.txt，状态也不应变化
    from domain.document.parser import DocumentParseError

    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager, data=b"   \r\n  ")

    with pytest.raises(DocumentParseError):
        parse_contract(contract.contract_id, manager)

    assert manager.get_contract(contract.contract_id).status is ContractStatus.UPLOADED
    assert not (tmp_path / "contracts" / contract.contract_id / "parsed_text.txt").exists()


def test_original_file_manually_removed_raises_not_found(tmp_path):
    manager = make_manager(tmp_path)
    contract = make_and_upload(tmp_path, manager)
    original = manager.get_original_file_path(contract.contract_id)
    original.unlink()

    with pytest.raises(ContractError):
        parse_contract(contract.contract_id, manager)
