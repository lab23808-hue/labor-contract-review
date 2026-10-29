"""Dense 检索后端：纯 Chroma store + DenseBackend。"""

from .backend import DenseBackend, build_dense_backend
from .store import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIR, ChromaVectorStore

__all__ = [
    "DenseBackend",
    "build_dense_backend",
    "ChromaVectorStore",
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_PERSIST_DIR",
]
