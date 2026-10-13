"""prompts/review.py 的单元测试：只测字符串拼装逻辑，不涉及网络。"""

from prompts.review import SYSTEM_PROMPT, build_review_messages
from schemas import Evidence


def make_evidence(article="第十九条", source="劳动合同法", content="试用期不得超过六个月。"):
    return Evidence(content=content, source=source, article=article, metadata={"score": 0.1})


def test_build_review_messages_returns_system_and_user():
    messages = build_review_messages("乙方工作地点为北京市。", "工作地点", [make_evidence()])

    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT


def test_user_message_includes_clause_text_and_type():
    messages = build_review_messages("乙方工作地点为北京市。", "工作地点", [make_evidence()])
    user_content = messages[1]["content"]

    assert "工作地点" in user_content
    assert "乙方工作地点为北京市。" in user_content


def test_user_message_includes_evidence_content_source_and_article():
    evidence = make_evidence(article="第二十条", source="劳动合同法", content="试用期工资不得低于百分之八十。")
    messages = build_review_messages("条款", "试用期", [evidence])
    user_content = messages[1]["content"]

    assert "劳动合同法" in user_content
    assert "第二十条" in user_content
    assert "试用期工资不得低于百分之八十。" in user_content


def test_multiple_evidence_are_all_included_and_numbered():
    evidences = [make_evidence(article="第十七条"), make_evidence(article="第十九条")]
    messages = build_review_messages("条款", "未知", evidences)
    user_content = messages[1]["content"]

    assert "[1]" in user_content
    assert "[2]" in user_content
    assert "第十七条" in user_content
    assert "第十九条" in user_content


def test_no_evidence_produces_explicit_placeholder():
    messages = build_review_messages("条款", "未知", [])
    assert "未检索到相关法律依据" in messages[1]["content"]


def test_evidence_without_article_does_not_crash():
    evidence = make_evidence(article=None)
    messages = build_review_messages("条款", "未知", [evidence])
    assert evidence.content in messages[1]["content"]


def test_system_prompt_requires_json_only_output():
    # DeepSeek 等 OpenAI 兼容服务的 JSON 模式要求 prompt 里明确提到 "json"
    assert "JSON" in SYSTEM_PROMPT or "json" in SYSTEM_PROMPT
