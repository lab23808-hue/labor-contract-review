"""rag/embedding.py 的单元测试。

只验证“wiring”：传给 HuggingFaceEmbeddings 的参数是否正确。用 unittest.mock.patch
替换掉真实的 HuggingFaceEmbeddings 类，绝不会真的下载/加载模型或请求网络
——真实的模型下载和向量生成效果需要在本地联网环境验证（例如跑
scripts/build_knowledge_base.py）。
"""

from unittest.mock import patch

from retrieval.embedding import DEFAULT_MODEL_NAME, build_embedder


def test_build_embedder_uses_bge_m3_by_default():
    with patch("retrieval.embedding.HuggingFaceEmbeddings") as mock_cls:
        build_embedder()
        _, kwargs = mock_cls.call_args

    assert kwargs["model_name"] == DEFAULT_MODEL_NAME == "BAAI/bge-m3"


def test_build_embedder_normalizes_embeddings():
    # BGE 系列官方推荐：归一化后向量内积等价于余弦相似度
    with patch("retrieval.embedding.HuggingFaceEmbeddings") as mock_cls:
        build_embedder()
        _, kwargs = mock_cls.call_args

    assert kwargs["encode_kwargs"] == {"normalize_embeddings": True}


def test_build_embedder_allows_custom_model_and_device():
    with patch("retrieval.embedding.HuggingFaceEmbeddings") as mock_cls:
        build_embedder(model_name="other/model", device="cuda")
        _, kwargs = mock_cls.call_args

    assert kwargs["model_name"] == "other/model"
    assert kwargs["model_kwargs"] == {"device": "cuda"}


def test_build_embedder_defaults_to_cpu():
    with patch("retrieval.embedding.HuggingFaceEmbeddings") as mock_cls:
        build_embedder()
        _, kwargs = mock_cls.call_args

    assert kwargs["model_kwargs"] == {"device": "cpu"}


def test_build_embedder_returns_constructed_instance():
    with patch("retrieval.embedding.HuggingFaceEmbeddings") as mock_cls:
        result = build_embedder()

    assert result is mock_cls.return_value
