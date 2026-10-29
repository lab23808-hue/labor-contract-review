"""review/reviewer.py（generate_query + ClauseReviewer）的单元测试。

用鸭子类型的假 retriever / 假 llm_client 注入，不依赖真实的 rag/llm 实现，
也不需要网络或真实的 BGE-M3 / DeepSeek。
"""

import pytest

from domain.agents.review_agent import ClauseReviewer, ReviewError, generate_query
from infra.llm import LLMClientError
from core import Clause, Evidence, ReviewSource, RiskLevel


def make_clause(original_text: str, clause_type: str = "unknown", clause_id: str = "clause_001") -> Clause:
    return Clause(
        contract_id="c1",
        clause_id=clause_id,
        clause_type=clause_type,
        original_text=original_text,
        start_char=0,
        end_char=len(original_text),
    )


def make_evidence(article="第二十条", content="试用期工资不得低于百分之八十。") -> Evidence:
    return Evidence(content=content, source="劳动合同法", article=article, metadata={"score": 0.1})


class FakeRetriever:
    """记录每次调用的 query/k，返回预设好的 Evidence 列表。"""

    def __init__(self, evidences=None, error: Exception = None):
        self.evidences = evidences if evidences is not None else [make_evidence()]
        self.error = error
        self.calls = []

    def search_legal_knowledge(self, query, k=None):
        self.calls.append({"query": query, "k": k})
        if self.error is not None:
            raise self.error
        return self.evidences


class FakeLLMClient:
    """记录每次调用的 messages，返回预设好的原始文本（或抛指定异常）。"""

    def __init__(self, response: str = None, error: Exception = None):
        self.response = response
        self.error = error
        self.calls = []

    def chat(self, messages, temperature=0.0, json_mode=False):
        self.calls.append({"messages": messages, "temperature": temperature, "json_mode": json_mode})
        if self.error is not None:
            raise self.error
        return self.response


VALID_LLM_JSON = (
    '{"risk": true, "risk_level": "high", "reason": "试用期工资低于法定最低标准",'
    ' "legal_basis": ["《劳动合同法》第二十条"], "suggestion": "调整为不低于百分之八十"}'
)


# ---------- generate_query ----------

def test_generate_query_keeps_heading_text_strips_only_the_number():
    clause = make_clause("第一条 试用期工资\n乙方试用期工资为正式工资的百分之五十。")
    assert generate_query(clause) == "试用期工资\n乙方试用期工资为正式工资的百分之五十。"


def test_generate_query_strips_numbered_item_prefix():
    clause = make_clause("1.乙方工作地点为北京市。")
    assert generate_query(clause) == "乙方工作地点为北京市。"


def test_generate_query_strips_chinese_bracket_item_prefix():
    clause = make_clause("（一）竞业限制期限为二年。")
    assert generate_query(clause) == "竞业限制期限为二年。"


def test_generate_query_plain_text_unchanged():
    clause = make_clause("乙方应遵守公司规章制度。")
    assert generate_query(clause) == "乙方应遵守公司规章制度。"


def test_generate_query_never_returns_empty_string():
    clause = make_clause("1.")
    assert generate_query(clause) == "1."


def test_generate_query_keeps_heading_keyword_not_present_in_body():
    # 回归用例：标题里的关键词（“竞业限制”）没有出现在正文里（正文是同义改写），
    # 之前把整行标题删掉会丢失这个关键词，导致真实检索验证时找不到相关法条。
    clause = make_clause(
        "第三条 竞业限制\n乙方在劳动合同解除或者终止后三年内，"
        "不得到与甲方有竞争关系的单位任职，甲方无需向乙方支付任何经济补偿。"
    )
    query = generate_query(clause)
    assert "竞业限制" in query
    assert "不得到与甲方有竞争关系的单位任职" in query


# ---------- ClauseReviewer.review：正常链路 ----------

def test_review_returns_review_result_with_expected_fields():
    clause = make_clause("第一条 试用期工资\n乙方试用期工资为正式工资的百分之五十。", clause_type="试用期工资")
    evidence = make_evidence()
    reviewer = ClauseReviewer(FakeRetriever(evidences=[evidence]), FakeLLMClient(response=VALID_LLM_JSON))

    result = reviewer.review(clause)

    assert result.clause_id == "clause_001"
    assert result.source == ReviewSource.LLM
    assert result.rule_id is None
    assert result.risk is True
    assert result.risk_level == RiskLevel.HIGH
    assert result.reason == "试用期工资低于法定最低标准"
    assert result.legal_basis == ["《劳动合同法》第二十条"]
    assert result.suggestion == "调整为不低于百分之八十"
    assert result.evidences == [evidence]


def test_review_with_explicit_evidence_does_not_retrieve():
    clause = make_clause("条款内容")
    evidence = make_evidence()
    retriever = FakeRetriever(error=RuntimeError("不应调用检索"))
    reviewer = ClauseReviewer(retriever, FakeLLMClient(response=VALID_LLM_JSON))

    result = reviewer.review(clause, [evidence])

    assert retriever.calls == []
    assert result.evidences == [evidence]


def test_review_uses_generated_query_for_retrieval():
    clause = make_clause("第一条 试用期工资\n乙方试用期工资为正式工资的百分之五十。")
    retriever = FakeRetriever()
    reviewer = ClauseReviewer(retriever, FakeLLMClient(response=VALID_LLM_JSON))

    reviewer.review(clause)

    assert retriever.calls[0]["query"] == "试用期工资\n乙方试用期工资为正式工资的百分之五十。"


def test_review_passes_top_k_to_retriever():
    clause = make_clause("条款内容")
    retriever = FakeRetriever()
    reviewer = ClauseReviewer(retriever, FakeLLMClient(response=VALID_LLM_JSON), top_k=7)

    reviewer.review(clause)

    assert retriever.calls[0]["k"] == 7


def test_review_calls_llm_with_json_mode():
    clause = make_clause("条款内容")
    llm_client = FakeLLMClient(response=VALID_LLM_JSON)
    reviewer = ClauseReviewer(FakeRetriever(), llm_client)

    reviewer.review(clause)

    assert llm_client.calls[0]["json_mode"] is True


def test_review_prompt_includes_clause_type_and_evidence():
    clause = make_clause("条款内容", clause_type="试用期工资")
    evidence = make_evidence(article="第二十条")
    llm_client = FakeLLMClient(response=VALID_LLM_JSON)
    reviewer = ClauseReviewer(FakeRetriever(evidences=[evidence]), llm_client)

    reviewer.review(clause)

    user_content = llm_client.calls[0]["messages"][1]["content"]
    assert "试用期工资" in user_content
    assert "第二十条" in user_content


def test_review_no_risk_result():
    clause = make_clause("条款内容")
    no_risk_json = '{"risk": false, "risk_level": "none", "reason": "符合规定", "legal_basis": [], "suggestion": ""}'
    reviewer = ClauseReviewer(FakeRetriever(), FakeLLMClient(response=no_risk_json))

    result = reviewer.review(clause)

    assert result.risk is False
    assert result.risk_level == RiskLevel.NONE


# ---------- 异常路径：不做静默兜底，全部抛 ReviewError ----------

def test_review_raises_when_retriever_fails():
    clause = make_clause("条款内容")
    reviewer = ClauseReviewer(FakeRetriever(error=RuntimeError("向量库连不上")), FakeLLMClient())

    with pytest.raises(ReviewError):
        reviewer.review(clause)


def test_review_raises_when_llm_client_fails():
    clause = make_clause("条款内容")
    reviewer = ClauseReviewer(FakeRetriever(), FakeLLMClient(error=LLMClientError("限流")))

    with pytest.raises(ReviewError):
        reviewer.review(clause)


def test_review_raises_on_non_json_output():
    clause = make_clause("条款内容")
    reviewer = ClauseReviewer(FakeRetriever(), FakeLLMClient(response="这不是 JSON"))

    with pytest.raises(ReviewError):
        reviewer.review(clause)


def test_review_raises_on_schema_violation():
    clause = make_clause("条款内容")
    # risk=true 但 risk_level=none，违反 LLMReviewOutput 自己的一致性校验
    bad_json = '{"risk": true, "risk_level": "none", "reason": "矛盾", "legal_basis": [], "suggestion": ""}'
    reviewer = ClauseReviewer(FakeRetriever(), FakeLLMClient(response=bad_json))

    with pytest.raises(ReviewError):
        reviewer.review(clause)


def test_review_raises_on_missing_required_field():
    clause = make_clause("条款内容")
    incomplete_json = '{"risk": true, "risk_level": "high"}'  # 缺 reason
    reviewer = ClauseReviewer(FakeRetriever(), FakeLLMClient(response=incomplete_json))

    with pytest.raises(ReviewError):
        reviewer.review(clause)
