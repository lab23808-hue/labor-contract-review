"""DenseBackend：BGE-M3 编码 + Chroma 查询 + Evidence/Document 转换。

职责边界：
    - EmbeddingService：文本 → 向量
    - ChromaVectorStore：向量 → 存储/最近邻查询
    - DenseBackend：把两者编排成 similarity_search / add_texts
"""

import uuid
from pathlib import Path
from typing import Optional, Union

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from retrieval.embedding import EmbeddingService

from .store import DEFAULT_COLLECTION_NAME, ChromaVectorStore


class DenseBackend:
    """可被 LegalKnowledgeRetriever 使用的 dense 检索后端。"""

    def __init__(
        self,
        embedding_function: Embeddings,
        store: Optional[ChromaVectorStore] = None,
        persist_directory: Optional[Union[str, Path]] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self.embedding = EmbeddingService(embedding_function)
        self.store = store or ChromaVectorStore(
            persist_directory=persist_directory,
            collection_name=collection_name or DEFAULT_COLLECTION_NAME,
        )

    def add_texts(
        self, texts: list[str], metadatas: list[dict], ids: Optional[list[str]] = None
    ) -> list[str]:
        if len(texts) != len(metadatas):
            raise ValueError("texts 和 metadatas 数量必须一致")
        if ids is not None and len(ids) != len(texts):
            raise ValueError("ids 和 texts 数量必须一致")
        if not texts:
            return []
        if ids is None:
            ids = [uuid.uuid4().hex for _ in texts]
        embeddings = self.embedding.embed_documents(texts)
        return self.store.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def similarity_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        if k <= 0:
            raise ValueError("k 必须大于 0")
        qvec = self.embedding.embed_query(query)
        res = self.store.query(query_embeddings=[qvec], n_results=k)

        docs = res["documents"][0]
        metas = res["metadatas"][0]
        dists = res["distances"][0]

        return [
            (Document(page_content=doc_text, metadata=meta or {}), float(dist))
            for doc_text, meta, dist in zip(docs, metas, dists)
        ]

    def count(self) -> int:
        return self.store.count()

    def reset(self) -> None:
        self.store.reset()


def build_dense_backend(
    embedding_function: Embeddings,
    persist_directory: Optional[Union[str, Path]] = None,
    collection_name: Optional[str] = None,
) -> DenseBackend:
    return DenseBackend(
        embedding_function=embedding_function,
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
