"""rag：法律知识库的切分、向量化、存储与检索。

只依赖 schemas（Evidence）和第三方库（LangChain、Chroma），
不依赖 contract / parser / clause，可以独立于合同处理流程单独使用和测试。
"""

from rag.database import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIR, ChromaKnowledgeBase
from rag.embedding import DEFAULT_MODEL_NAME, build_embedder
from rag.knowledge_loader import KnowledgeLoader
from rag.retriever import LegalKnowledgeRetriever

__all__ = [
    "ChromaKnowledgeBase",
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_PERSIST_DIR",
    "build_embedder",
    "DEFAULT_MODEL_NAME",
    "KnowledgeLoader",
    "LegalKnowledgeRetriever",
]
