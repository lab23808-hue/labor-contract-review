"""rag/database.py（ChromaKnowledgeBase）的单元测试。运行：在项目根目录执行 `pytest`。"""

import pytest

from rag.database import ChromaKnowledgeBase
from tests._rag_fakes import FakeEmbeddings


def make_kb(tmp_path, collection_name="test_collection") -> ChromaKnowledgeBase:
    return ChromaKnowledgeBase(
        embedding_function=FakeEmbeddings(),
        persist_directory=tmp_path / "chroma",
        collection_name=collection_name,
    )


# ---------- 知识文本入库 / Chroma 保存 ----------

def test_add_texts_increases_count(tmp_path):
    kb = make_kb(tmp_path)
    assert kb.count() == 0

    ids = kb.add_texts(["第一条 内容", "第二条 内容"], [{"source": "法A"}, {"source": "法A"}])

    assert len(ids) == 2
    assert len(set(ids)) == 2  # id 各不相同
    assert kb.count() == 2


def test_add_texts_with_explicit_ids(tmp_path):
    kb = make_kb(tmp_path)
    ids = kb.add_texts(["内容"], [{"source": "法A"}], ids=["my-id-1"])
    assert ids == ["my-id-1"]


def test_add_empty_list_is_a_no_op(tmp_path):
    kb = make_kb(tmp_path)
    assert kb.add_texts([], []) == []
    assert kb.count() == 0


def test_add_texts_validates_lengths_match(tmp_path):
    kb = make_kb(tmp_path)
    with pytest.raises(ValueError):
        kb.add_texts(["a", "b"], [{"source": "法A"}])
    with pytest.raises(ValueError):
        kb.add_texts(["a"], [{"source": "法A"}], ids=["1", "2"])


def test_persists_across_new_instances_with_same_location(tmp_path):
    # 同一个 (persist_directory, collection_name)：重新创建实例应能看到之前写入的数据
    kb1 = make_kb(tmp_path)
    kb1.add_texts(["第一条 内容"], [{"source": "法A"}])

    kb2 = make_kb(tmp_path)
    assert kb2.count() == 1


def test_different_collection_names_are_isolated(tmp_path):
    kb_a = make_kb(tmp_path, collection_name="collection_a")
    kb_b = make_kb(tmp_path, collection_name="collection_b")

    kb_a.add_texts(["内容"], [{"source": "法A"}])

    assert kb_a.count() == 1
    assert kb_b.count() == 0


# ---------- embedding 生成 ----------

def test_add_texts_calls_embedding_function(tmp_path):
    embedder = FakeEmbeddings()
    kb = ChromaKnowledgeBase(embedder, persist_directory=tmp_path / "chroma")

    kb.add_texts(["第一条 内容", "第二条 内容"], [{"source": "法A"}, {"source": "法A"}])

    assert embedder.embed_documents_calls == [["第一条 内容", "第二条 内容"]]


def test_similarity_search_calls_embed_query(tmp_path):
    embedder = FakeEmbeddings()
    kb = ChromaKnowledgeBase(embedder, persist_directory=tmp_path / "chroma")
    kb.add_texts(["第一条 内容"], [{"source": "法A"}])

    kb.similarity_search("查询文本", k=1)

    assert embedder.embed_query_calls == ["查询文本"]


# ---------- query 检索 ----------

def test_similarity_search_returns_document_and_score(tmp_path):
    kb = make_kb(tmp_path)
    kb.add_texts(["试用期不得超过六个月", "竞业限制不得超过二年"], [{"source": "法A"}, {"source": "法A"}])

    results = kb.similarity_search("试用期不得超过六个月", k=1)

    assert len(results) == 1
    doc, score = results[0]
    assert doc.page_content == "试用期不得超过六个月"
    assert isinstance(score, float)


def test_similarity_search_respects_k(tmp_path):
    kb = make_kb(tmp_path)
    kb.add_texts([f"第{i}条 内容{i}" for i in range(5)], [{"source": "法A"}] * 5)

    assert len(kb.similarity_search("内容", k=3)) == 3
    assert len(kb.similarity_search("内容", k=100)) == 5  # 不足 k 时返回全部，不报错


def test_similarity_search_rejects_non_positive_k(tmp_path):
    kb = make_kb(tmp_path)
    with pytest.raises(ValueError):
        kb.similarity_search("内容", k=0)


# ---------- reset ----------

def test_reset_clears_all_documents(tmp_path):
    kb = make_kb(tmp_path)
    kb.add_texts(["内容"], [{"source": "法A"}])
    assert kb.count() == 1

    kb.reset()

    assert kb.count() == 0


def test_can_add_again_after_reset(tmp_path):
    kb = make_kb(tmp_path)
    kb.add_texts(["旧内容"], [{"source": "法A"}])
    kb.reset()

    kb.add_texts(["新内容"], [{"source": "法B"}])

    assert kb.count() == 1
    doc, _ = kb.similarity_search("新内容", k=1)[0]
    assert doc.page_content == "新内容"
