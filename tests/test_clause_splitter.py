"""ClauseSplitter 的单元测试。运行：在项目根目录执行 `pytest`。"""

import pytest

from document import ClauseSplitter

CID = "contract_001"

# 规范里的示例
SAMPLE = "第三条 工作地点\n\n1.乙方工作地点为北京市。\n\n2.甲方可以根据经营需要调整工作地点。"

CONTRACT = """劳动合同书

甲方：某某公司
乙方：张三

第一条 合同期限
本合同自2024年1月1日起至2026年12月31日止。

第二条 试用期 试用期为三个月，试用期工资为正式工资的80%。

第三条 工作地点
1.乙方工作地点为北京市。
2.甲方可以根据经营需要调整工作地点。

第四条 违约责任
（一）乙方违反保密义务的，应支付违约金。
  1. 违约金标准为十万元。
（二）甲方拖欠工资的，应依法支付经济补偿。
"""


def assert_offsets_valid(text, clauses):
    """核心不变量：按偏移量从全文取出的内容必须等于 original_text。"""
    for c in clauses:
        assert text[c.start_char : c.end_char] == c.original_text, c.clause_id
    assert len({c.clause_id for c in clauses}) == len(clauses), "clause_id 必须唯一"


# ---------- 规范示例 ----------

def test_spec_example_article_with_items():
    clauses = ClauseSplitter().split(SAMPLE, CID)

    assert [c.clause_id for c in clauses] == ["clause_001", "clause_001_1", "clause_001_2"]
    assert [c.hierarchy_level for c in clauses] == [0, 1, 1]
    assert [c.parent_clause for c in clauses] == [None, "clause_001", "clause_001"]
    assert clauses[0].original_text == "第三条 工作地点"
    assert clauses[1].original_text == "1.乙方工作地点为北京市。"
    assert clauses[2].original_text == "2.甲方可以根据经营需要调整工作地点。"
    assert clauses[1].metadata["article_no"] == "第三条"
    assert clauses[1].metadata["article_title"] == "第三条 工作地点"
    assert all(c.page_number is None for c in clauses)
    assert_offsets_valid(SAMPLE, clauses)


# ---------- 完整合同 ----------

def test_full_contract_structure():
    clauses = ClauseSplitter().split(CONTRACT, CID)

    assert [c.clause_id for c in clauses] == [
        "clause_000",  # 前言
        "clause_001",
        "clause_002",
        "clause_003", "clause_003_1", "clause_003_2",
        "clause_004", "clause_004_1", "clause_004_2",
    ]
    assert clauses[0].clause_type == "preamble"
    assert "甲方：某某公司" in clauses[0].original_text
    assert_offsets_valid(CONTRACT, clauses)


def test_clauses_are_ordered_and_do_not_overlap():
    clauses = ClauseSplitter().split(CONTRACT, CID)
    for prev, cur in zip(clauses, clauses[1:]):
        assert prev.end_char <= cur.start_char


def test_article_without_items_stays_one_clause():
    # 标题和正文写在同一行
    clauses = ClauseSplitter().split(CONTRACT, CID)
    c = next(c for c in clauses if c.clause_id == "clause_002")
    assert c.original_text.startswith("第二条 试用期")
    assert "80%" in c.original_text


def test_nested_numbering_stays_inside_parent_item():
    # 条下用“（一）”时，其中嵌套的“1.”不能被误切成同级的款
    clauses = ClauseSplitter().split(CONTRACT, CID)
    item = next(c for c in clauses if c.clause_id == "clause_004_1")
    assert "违约金标准为十万元" in item.original_text
    assert len([c for c in clauses if c.parent_clause == "clause_004"]) == 2


def test_decimal_at_line_start_is_not_an_item():
    text = "第一条 工资\n1.5倍工资适用于加班。"
    clauses = ClauseSplitter().split(text, CID)
    assert [c.clause_id for c in clauses] == ["clause_001"]


def test_line_start_reference_is_not_an_article_heading():
    text = "第一条 违约\n乙方违约的，依照\n第三十九条的规定处理。\n第二条 其他\n无。"
    clauses = ClauseSplitter().split(text, CID)
    assert [c.clause_id for c in clauses] == ["clause_001", "clause_002"]
    assert_offsets_valid(text, clauses)


# ---------- 边界情况 ----------

def test_empty_and_whitespace_text():
    assert ClauseSplitter().split("", CID) == []
    assert ClauseSplitter().split("  \n \n", CID) == []


def test_text_without_articles_becomes_single_clause():
    text = "本合同一式两份，双方各执一份。"
    clauses = ClauseSplitter().split(text, CID)
    assert len(clauses) == 1
    assert clauses[0].clause_id == "clause_001"
    assert clauses[0].metadata["structure"] == "none"
    assert_offsets_valid(text, clauses)


def test_crlf_line_endings():
    text = SAMPLE.replace("\n", "\r\n")
    clauses = ClauseSplitter().split(text, CID)
    assert [c.clause_id for c in clauses] == ["clause_001", "clause_001_1", "clause_001_2"]
    assert clauses[0].original_text == "第三条 工作地点"
    assert_offsets_valid(text, clauses)


# ---------- 过长条款的二次切分 ----------

def test_oversized_item_is_split_with_valid_offsets():
    long_item = "".join(f"第{i}项义务：乙方应当遵守规章制度。" for i in range(30))
    text = f"第一条 制度\n1.{long_item}"
    clauses = ClauseSplitter(chunk_size=100, chunk_overlap=20).split(text, CID)

    parts = [c for c in clauses if c.metadata.get("split_from") == "clause_001_1"]
    assert len(parts) > 1
    for i, c in enumerate(parts, start=1):
        assert len(c.original_text) <= 100
        assert c.clause_id == f"clause_001_1_p{i}"
        assert c.parent_clause == "clause_001"
        assert c.hierarchy_level == 1
        assert c.metadata["part"] == i and c.metadata["parts"] == len(parts)
    assert all(a.start_char < b.start_char for a, b in zip(parts, parts[1:]))
    # 各段合起来覆盖整个款：从“1.”开头，到全文末尾
    assert parts[0].start_char == text.index("1.")
    assert parts[-1].end_char == len(text)
    assert_offsets_valid(text, clauses)


def test_short_clauses_are_never_split():
    clauses = ClauseSplitter(chunk_size=500).split(CONTRACT, CID)
    assert not any("split_from" in c.metadata for c in clauses)


# ---------- 参数校验 ----------

def test_invalid_parameters():
    with pytest.raises(ValueError):
        ClauseSplitter(chunk_size=0)
    with pytest.raises(ValueError):
        ClauseSplitter(chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        ClauseSplitter(chunk_size=100, chunk_overlap=-1)


# ---------- contract_id ----------

def test_contract_id_is_set_on_every_clause():
    clauses = ClauseSplitter(chunk_size=100, chunk_overlap=20).split(CONTRACT, "contract_xyz")
    assert clauses
    assert {c.contract_id for c in clauses} == {"contract_xyz"}


def test_empty_contract_id_rejected():
    with pytest.raises(ValueError):  # pydantic 的 ValidationError 是 ValueError 的子类
        ClauseSplitter().split(SAMPLE, "")
