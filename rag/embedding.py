"""统一构造 Embedding 函数（当前使用 BGE-M3）。

只在这里指定“用哪个模型、传什么参数”；其余模块（database.py / loader.py / retrieval.py）
只依赖 LangChain 的 Embeddings 接口（embed_documents / embed_query），不关心具体实现。
以后要换模型、换成调用 API 的方案，只需要改这一个文件。

BGE-M3（BAAI/bge-m3）原生支持稠密、稀疏、ColBERT 三种向量。这里通过
langchain-huggingface 的 HuggingFaceEmbeddings 只使用其中的稠密向量，
足够满足当前“基础语义检索”的需要。以后如果要做稀疏/多向量混合检索，
需要换用 FlagEmbedding 官方库重写本文件，其余模块不受影响。

首次调用 build_embedder() 会从 HuggingFace 下载模型权重（需要联网，或提前缓存好），
单元测试里用 unittest.mock 替换 HuggingFaceEmbeddings，不会触发下载（见 tests/test_rag_embedding.py）。
"""

from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings

from config import settings

DEFAULT_MODEL_NAME = settings.EMBEDDING_MODEL_NAME


def build_embedder(model_name: str = DEFAULT_MODEL_NAME, device: str = "cpu") -> Embeddings:
    """构造一个 Embeddings 实例。

    normalize_embeddings=True：归一化后向量的内积等价于余弦相似度，
    这是 BGE 系列模型官方推荐的用法，能让检索结果的相似度分数更稳定。
    """
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},
    )
