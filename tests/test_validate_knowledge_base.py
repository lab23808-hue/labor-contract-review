"""scripts/validate_knowledge_base.py 的单元测试（纯标准库，不依赖 chromadb/
langchain_text_splitters——这正是这个脚本存在的原因：生产代码的
KnowledgeLoader 因为模块顶层 import 了 langchain_text_splitters，没法在
本沙箱里哪怕只测"按第X条切分"这一步纯文本逻辑；这里独立测试同一份正则。
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "validate_knowledge_base.py"
_spec = importlib.util.spec_from_file_location("validate_knowledge_base", _SCRIPT_PATH)
vkb = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(_SCRIPT_PATH.parent.parent))
_spec.loader.exec_module(vkb)


def test_cn_number_to_int_handles_two_digit_and_bare_numbers():
    assert vkb._cn_number_to_int("二十") == 20
    assert vkb._cn_number_to_int("二十一") == 21
    assert vkb._cn_number_to_int("八十五") == 85
    assert vkb._cn_number_to_int("八十七") == 87
    assert vkb._cn_number_to_int("十七") == 17
    assert vkb._cn_number_to_int("十九") == 19
    assert vkb._cn_number_to_int("三") == 3
    assert vkb._cn_number_to_int("一") == 1


def test_find_article_spans_splits_on_each_article_heading():
    text = "第一条　内容一。\n\n第二条　内容二，比较长。\n\n第十条　内容十。"
    spans = vkb.find_article_spans(text)
    labels = [label for _, _, label in spans]
    assert labels == ["第一条", "第二条", "第十条"]


def test_find_article_spans_excludes_cross_reference_followed_by_de():
    # "……依照第三十九条的规定" 不应该被当成一个新条文的开头（已有正则里的 (?!的) 排除逻辑）
    text = "第一条　依照第三十九条的规定处理。\n\n第二条　另一条内容。"
    spans = vkb.find_article_spans(text)
    labels = [label for _, _, label in spans]
    assert labels == ["第一条", "第二条"]


def test_validate_file_detects_duplicate_article_number(tmp_path):
    f = tmp_path / "dup.txt"
    f.write_text("第一条　内容一。\n\n第一条　重复的条号。\n", encoding="utf-8")

    report = vkb.validate_file(f, chunk_size=500)

    assert len(report["duplicate_articles"]) == 1
    assert report["duplicate_articles"][0]["article"] == "第一条"


def test_validate_file_flags_oversized_article(tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("第一条　" + "很长的条文内容。" * 100, encoding="utf-8")

    report = vkb.validate_file(f, chunk_size=50)

    assert len(report["oversized_articles"]) == 1
    assert report["oversized_articles"][0]["article"] == "第一条"


def test_validate_file_no_false_positive_on_clean_file(tmp_path):
    f = tmp_path / "clean.txt"
    f.write_text("第一条　内容一。\n\n第二条　内容二。\n\n第三条　内容三。\n", encoding="utf-8")

    report = vkb.validate_file(f, chunk_size=500)

    assert report["duplicate_articles"] == []
    assert report["empty_blocks"] == []
    assert report["oversized_articles"] == []
    assert report["unparsable_numbers"] == []
    assert report["article_count"] == 3


def test_real_knowledge_base_file_has_no_duplicate_or_empty_articles():
    """对项目里真实的 data/knowledge/劳动合同法.txt 跑一次，确认本次扩充没有引入
    重复条号或空块（这是本次新增 12 条之后最基本的健全性检查）。
    """
    from config import settings

    kb_file = settings.KNOWLEDGE_DIR / "劳动合同法.txt"
    report = vkb.validate_file(kb_file, chunk_size=settings.KNOWLEDGE_CHUNK_SIZE)

    assert report["duplicate_articles"] == []
    assert report["empty_blocks"] == []
    assert report["unparsable_numbers"] == []
    # 本次扩充前是 14 条，新增 12 条后应为 26 条——用具体数字而不是 >= 防止
    # 以后有人不小心删了条文却没人发现。
    assert report["article_count"] == 26
