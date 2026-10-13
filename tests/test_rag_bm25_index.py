"""rag/bm25_index.py（BM25KnowledgeIndex）的单元测试。

纯内存实现，不依赖 chromadb/BGE-M3，可以在没有这些重依赖的环境里跑——这也是
选它作为 BM25 默认策略底层实现的原因之一。运行：在项目根目录执行 `pytest`。
"""

import pytest

from rag.bm25_index import BM25IndexBuildError, BM25KnowledgeIndex, char_bigram_tokenizer
from schemas import Evidence


def _evidence(content, source="劳动合同法", article=None, metadata=None):
    return Evidence(content=content, source=source, article=article, metadata=metadata or {})


# ---------- 分词器：与实验脚本里已验证过的实现逐行核对 ----------

def test_char_bigram_tokenizer_pairs_adjacent_non_space_chars():
    assert char_bigram_tokenizer("甲乙丙") == ["甲乙", "乙丙"]


def test_char_bigram_tokenizer_strips_whitespace_before_pairing():
    assert char_bigram_tokenizer("甲 乙丙") == ["甲乙", "乙丙"]


def test_char_bigram_tokenizer_handles_single_char():
    assert char_bigram_tokenizer("甲") == ["甲"]


def test_char_bigram_tokenizer_handles_empty_string():
    assert char_bigram_tokenizer("") == []


# ---------- 构建期校验：空知识库 / 无效条文 / 重复条目 ----------

def test_build_rejects_empty_evidence_list():
    with pytest.raises(BM25IndexBuildError):
        BM25KnowledgeIndex([])


def test_build_rejects_blank_content():
    # Evidence.content 只校验 min_length=1，不校验"全是空白"，
    # 所以这个检查必须在 BM25KnowledgeIndex 自己做。
    with pytest.raises(BM25IndexBuildError):
        BM25KnowledgeIndex([_evidence("   ", article="第一条")])


def test_build_rejects_duplicate_evidence_and_error_names_the_conflict():
    e1 = _evidence("完全相同的条文内容", article="第一条")
    e2 = _evidence("完全相同的条文内容", article="第一条")
    with pytest.raises(BM25IndexBuildError) as exc_info:
        BM25KnowledgeIndex([e1, e2])
    message = str(exc_info.value)
    assert "第一条" in message
    assert "劳动合同法" in message


def test_build_does_not_treat_similar_but_different_content_as_duplicate():
    # 内容相近但不完全相同——不应该被判重（判重只看内容哈希，不看文本相似度）。
    e1 = _evidence("试用期不得超过一个月", article="第一条")
    e2 = _evidence("试用期不得超过两个月", article="第二条")
    index = BM25KnowledgeIndex([e1, e2])
    assert index.count() == 2


def test_build_accepts_evidences_with_different_parts_of_same_article():
    # 同一条被二次切分出来的多个 part，(source, article, part, content) 不同，
    # 不应该被误判为重复——与 KnowledgeLoader._evidence_id() 的设计一致。
    e1 = _evidence("第一部分", article="第一条", metadata={"part": 1, "parts": 2})
    e2 = _evidence("第二部分", article="第一条", metadata={"part": 2, "parts": 2})
    index = BM25KnowledgeIndex([e1, e2])
    assert index.count() == 2


# ---------- 检索行为 ----------

def test_similarity_search_ranks_lexically_overlapping_doc_first():
    e1 = _evidence("试用期不得超过一个月", article="第十九条")
    e2 = _evidence("竞业限制期限不得超过二年", article="第二十四条")
    index = BM25KnowledgeIndex([e1, e2])

    results = index.similarity_search("试用期最长可以约定多久", k=1)

    assert len(results) == 1
    doc, score = results[0]
    assert doc.metadata["article"] == "第十九条"
    assert isinstance(score, float)


def test_similarity_search_respects_k():
    evidences = [_evidence(f"第{i}条内容文本", article=f"第{i}条") for i in range(5)]
    index = BM25KnowledgeIndex(evidences)
    assert len(index.similarity_search("内容文本", k=3)) == 3


def test_similarity_search_rejects_non_positive_k():
    index = BM25KnowledgeIndex([_evidence("内容", article="第一条")])
    with pytest.raises(ValueError):
        index.similarity_search("内容", k=0)


def test_similarity_search_document_metadata_matches_evidence_and_is_tagged():
    e = _evidence("试用期相关内容", source="劳动合同法", article="第十九条")
    index = BM25KnowledgeIndex([e])

    doc, _score = index.similarity_search("试用期", k=1)[0]

    assert doc.page_content == "试用期相关内容"
    assert doc.metadata["source"] == "劳动合同法"
    assert doc.metadata["article"] == "第十九条"
    assert doc.metadata["score_type"] == "bm25_okapi_char_bigram"


def test_count_matches_number_of_evidences():
    evidences = [_evidence(f"内容{i}", article=f"第{i}条") for i in range(3)]
    index = BM25KnowledgeIndex(evidences)
    assert index.count() == 3


# ---------- 与 LegalKnowledgeRetriever 的集成：确认统一接口真的兼容 ----------

def test_bm25_index_satisfies_retriever_contract_end_to_end():
    from rag.retriever import LegalKnowledgeRetriever

    evidences = [
        _evidence("劳动合同期限三个月以上不满一年的，试用期不得超过一个月。", article="第十九条"),
        _evidence("竞业限制期限不得超过二年。", article="第二十四条"),
    ]
    index = BM25KnowledgeIndex(evidences)
    retriever = LegalKnowledgeRetriever(knowledge_base=index, top_k=1)

    results = retriever.search_legal_knowledge("试用期最长可以约定多久？")

    assert len(results) == 1
    assert results[0].article == "第十九条"
    assert results[0].metadata["score_type"] == "bm25_okapi_char_bigram"
