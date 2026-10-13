"""rag/retriever.py（LegalKnowledgeRetriever）的单元测试。运行：在项目根目录执行 `pytest`。"""

import pytest

from rag.database import ChromaKnowledgeBase
from rag.retriever import LegalKnowledgeRetriever
from schemas import Evidence
from tests._rag_fakes import FakeEmbeddings


def make_retriever(tmp_path, **kwargs) -> LegalKnowledgeRetriever:
    kb = ChromaKnowledgeBase(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    kb.add_texts(
        ["劳动合同期限三个月以上不满一年的，试用期不得超过一个月。", "竞业限制期限不得超过二年。"],
        [{"source": "劳动合同法", "article": "第十九条"}, {"source": "劳动合同法", "article": "第二十四条"}],
    )
    return LegalKnowledgeRetriever(kb, **kwargs)


# ---------- query 检索：返回相关结果 ----------

def test_search_returns_most_relevant_article_first(tmp_path):
    retriever = make_retriever(tmp_path)

    results = retriever.search_legal_knowledge("试用期最长可以约定多久？", k=1)

    assert len(results) == 1
    assert results[0].article == "第十九条"


def test_search_respects_default_top_k(tmp_path):
    retriever = make_retriever(tmp_path, top_k=1)
    assert len(retriever.search_legal_knowledge("试用期")) == 1


def test_search_k_overrides_default_top_k(tmp_path):
    retriever = make_retriever(tmp_path, top_k=1)
    assert len(retriever.search_legal_knowledge("试用期", k=2)) == 2


def test_search_rejects_empty_query(tmp_path):
    retriever = make_retriever(tmp_path)
    with pytest.raises(ValueError):
        retriever.search_legal_knowledge("")
    with pytest.raises(ValueError):
        retriever.search_legal_knowledge("   ")


def test_retriever_rejects_non_positive_top_k(tmp_path):
    kb = ChromaKnowledgeBase(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    with pytest.raises(ValueError):
        LegalKnowledgeRetriever(kb, top_k=0)


# ---------- 返回 Evidence 格式正确 ----------

def test_search_returns_evidence_instances(tmp_path):
    results = make_retriever(tmp_path).search_legal_knowledge("试用期", k=2)

    assert all(isinstance(e, Evidence) for e in results)


def test_evidence_fields_populated_correctly(tmp_path):
    results = make_retriever(tmp_path).search_legal_knowledge("试用期最长可以约定多久？", k=1)
    evidence = results[0]

    assert evidence.source == "劳动合同法"
    assert evidence.article == "第十九条"
    assert evidence.content == "劳动合同期限三个月以上不满一年的，试用期不得超过一个月。"
    assert "score" in evidence.metadata
    assert isinstance(evidence.metadata["score"], float)


def test_evidence_metadata_does_not_duplicate_source_and_article(tmp_path):
    # source/article 是 Evidence 的一等字段，不应该在 metadata 里重复出现
    evidence = make_retriever(tmp_path).search_legal_knowledge("试用期", k=1)[0]

    assert "source" not in evidence.metadata
    assert "article" not in evidence.metadata


def test_evidence_survives_json_roundtrip(tmp_path):
    evidence = make_retriever(tmp_path).search_legal_knowledge("试用期", k=1)[0]
    assert Evidence.model_validate_json(evidence.model_dump_json()) == evidence


def test_search_on_empty_knowledge_base_returns_empty_list(tmp_path):
    kb = ChromaKnowledgeBase(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    retriever = LegalKnowledgeRetriever(kb)

    assert retriever.search_legal_knowledge("任意查询") == []
