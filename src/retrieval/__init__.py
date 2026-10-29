"""检索层：知识库切分、向量化、存储与后端。

目录职责：
    - embedding.py               文本 → 向量（BGE-M3）
    - backends/dense/store.py    纯 Chroma 连接/读写/查询
    - backends/dense/backend.py  DenseBackend：embedding + store + 结果转换
    - backends/lexical/          BM25Index + BM25Backend
    - knowledge_loader.py        文档 → Evidence → 写入后端
    - retriever.py               LegalKnowledgeRetriever：Document → Evidence
"""

from retrieval.backends.dense import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_PERSIST_DIR,
    ChromaVectorStore,
    DenseBackend,
    build_dense_backend,
)
from retrieval.backends.lexical import (
    SCORE_TYPE,
    BM25Backend,
    BM25Index,
    BM25IndexBuildError,
    char_bigram_tokenizer,
)
from retrieval.base import SimilaritySearchBackend, VectorSink
from retrieval.embedding import DEFAULT_MODEL_NAME, EmbeddingService, build_embedder
from retrieval.knowledge_loader import KnowledgeLoader
from retrieval.retriever import LegalKnowledgeRetriever

__all__ = [
    "ChromaVectorStore",
    "DenseBackend",
    "build_dense_backend",
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_PERSIST_DIR",
    "EmbeddingService",
    "build_embedder",
    "DEFAULT_MODEL_NAME",
    "KnowledgeLoader",
    "LegalKnowledgeRetriever",
    "SimilaritySearchBackend",
    "VectorSink",
    "BM25Backend",
    "BM25Index",
    "BM25IndexBuildError",
    "char_bigram_tokenizer",
    "SCORE_TYPE",
]
