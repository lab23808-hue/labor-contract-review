"""rag：法律知识库的切分、向量化、存储与检索。

只依赖 schemas（Evidence）和第三方库（LangChain、Chroma），
不依赖 contract / parser / clause，可以独立于合同处理流程单独使用和测试。

2026-10-12 正式接入 BM25：`BM25KnowledgeIndex` 是与 `ChromaKnowledgeBase`
平级的另一种检索后端（纯内存、纯标准库，不依赖 Chroma/BGE-M3），两者都满足
`rag.retriever.SimilaritySearchBackend` 这个结构化接口。
"""

from rag.bm25_index import SCORE_TYPE, BM25IndexBuildError, BM25KnowledgeIndex, char_bigram_tokenizer
from rag.database import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIR, ChromaKnowledgeBase
from rag.embedding import DEFAULT_MODEL_NAME, build_embedder
from rag.knowledge_loader import KnowledgeLoader
from rag.retriever import LegalKnowledgeRetriever, SimilaritySearchBackend

__all__ = [
    "ChromaKnowledgeBase",
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_PERSIST_DIR",
    "build_embedder",
    "DEFAULT_MODEL_NAME",
    "KnowledgeLoader",
    "LegalKnowledgeRetriever",
    "SimilaritySearchBackend",
    "BM25KnowledgeIndex",
    "BM25IndexBuildError",
    "char_bigram_tokenizer",
    "SCORE_TYPE",
]
