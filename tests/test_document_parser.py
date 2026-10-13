"""DocumentParser 的单元测试。运行：在项目根目录执行 `pytest`。"""

import pytest

from document import (
    BaseParser,
    ClauseSplitter,
    DocumentParseError,
    DocumentParser,
    TxtParser,
    UnsupportedFormatError,
)

CID = "contract_001"
TEXT = "劳动合同\n\n第一条 合同期限\n本合同期限三年。\n\n第二条 工作地点\n1.北京市。\n2.可调整。\n"


# ---------- 不改动原文 ----------

def test_text_is_returned_unchanged():
    # 首尾空白、空行、CRLF、全角空格都必须原样保留
    original = "  \n第一条\u3000内容\r\n\r\n  尾部空白  \n\n"
    assert DocumentParser().parse_bytes(original.encode("utf-8"), "a.txt") == original


def test_crlf_is_not_translated_when_reading_file(tmp_path):
    raw = "第一条 内容\r\n第二条 内容\r\n".encode("utf-8")
    f = tmp_path / "c.txt"
    f.write_bytes(raw)
    assert DocumentParser().parse_file(f).count("\r\n") == 2


# ---------- 编码 ----------

def test_utf8_bom_is_removed_but_content_kept():
    data = b"\xef\xbb\xbf" + "第一条 内容".encode("utf-8")
    text = DocumentParser().parse_bytes(data, "a.txt")
    assert text == "第一条 内容"  # 不含 \ufeff


def test_plain_utf8_detected():
    assert TxtParser.decode(TEXT.encode("utf-8")) == (TEXT, "utf-8-sig")


def test_gbk_detected():
    data = TEXT.encode("gbk")
    text, encoding = TxtParser.decode(data)
    assert text == TEXT
    assert encoding == "gb18030"


def test_utf16_with_bom_detected():
    text, encoding = TxtParser.decode(TEXT.encode("utf-16"))  # 自带 BOM
    assert text == TEXT
    assert encoding == "utf-16"


def test_undecodable_bytes_rejected():
    with pytest.raises(DocumentParseError):
        DocumentParser().parse_bytes(b"\xff\xff\xff\xff", "a.txt")


def test_binary_like_content_rejected():
    with pytest.raises(DocumentParseError):
        DocumentParser().parse_bytes(b"abc\x00\x01\x02def", "a.txt")


# ---------- 空内容 ----------

def test_empty_and_blank_files_rejected():
    with pytest.raises(DocumentParseError):
        DocumentParser().parse_bytes(b"", "a.txt")
    with pytest.raises(DocumentParseError):
        DocumentParser().parse_bytes(" \r\n\t\n".encode("utf-8"), "a.txt")


# ---------- 格式分发 ----------

def test_suffix_is_case_insensitive():
    assert DocumentParser().parse_bytes(TEXT.encode("utf-8"), "合同.TXT") == TEXT


def test_parse_file_accepts_str_and_path(tmp_path):
    f = tmp_path / "c.txt"
    f.write_bytes(TEXT.encode("utf-8"))
    assert DocumentParser().parse_file(f) == TEXT
    assert DocumentParser().parse_file(str(f)) == TEXT


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        DocumentParser().parse_file(tmp_path / "nope.txt")


def test_unknown_or_missing_suffix_rejected():
    with pytest.raises(UnsupportedFormatError):
        DocumentParser().parse_bytes(b"x", "a.xyz")
    with pytest.raises(UnsupportedFormatError):
        DocumentParser().parse_bytes(b"x", "contract")


def test_reserved_formats_raise_not_implemented():
    for name in ("a.pdf", "a.docx", "a.png"):
        with pytest.raises(NotImplementedError):
            DocumentParser().parse_bytes(b"x", name)


def test_parser_list_can_be_customized():
    only_txt = DocumentParser(parsers=[TxtParser()])
    with pytest.raises(UnsupportedFormatError):  # 没注册 pdf，就是“不支持”而不是“未实现”
        only_txt.parse_bytes(b"x", "a.pdf")


def test_register_custom_parser_extension_point():
    class MdParser(BaseParser):
        suffixes = (".md",)

        def parse_bytes(self, data: bytes) -> str:
            return data.decode("utf-8")

    parser = DocumentParser()
    parser.register(MdParser())
    assert parser.parse_bytes(b"# title", "a.MD") == "# title"


# ---------- 与 ClauseSplitter 衔接 ----------

def test_output_feeds_clause_splitter_with_valid_offsets(tmp_path):
    # 带 BOM + CRLF 的常见 Windows 文本
    raw = TEXT.replace("\n", "\r\n").encode("utf-8-sig")
    f = tmp_path / "contract.txt"
    f.write_bytes(raw)

    text = DocumentParser().parse_file(f)
    clauses = ClauseSplitter().split(text, CID)

    assert [c.clause_id for c in clauses] == [
        "clause_000", "clause_001", "clause_002", "clause_002_1", "clause_002_2",
    ]
    for c in clauses:
        assert text[c.start_char : c.end_char] == c.original_text
