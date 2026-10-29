"""ChromaVectorStore：纯 Chroma 连接与读写适配器。

只负责：
    - 创建/打开 PersistentClient + collection
    - upsert(ids, documents, embeddings, metadatas)
    - query(query_embeddings, n_results)
    - count / reset

不负责：
    - 文本向量化（EmbeddingService）
    - query 文本 → 向量
    - Document / Evidence 转换
    - 检索编排（DenseBackend）

这样换 embedding 模型、换向量库、加 hybrid 融合时，不需要改本文件。
"""

from pathlib import Path
from typing import Union

import chromadb

from config import settings

DEFAULT_PERSIST_DIR = settings.CHROMA_DIR
DEFAULT_COLLECTION_NAME = settings.CHROMA_COLLECTION_NAME


class ChromaVectorStore:
    """对某个 Chroma collection 的纯存储连接。"""

    def __init__(
        self,
        persist_directory: Union[str, Path, None] = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        self.persist_directory = Path(persist_directory) if persist_directory is not None else DEFAULT_PERSIST_DIR
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._client = chromadb.PersistentClient(path=str(self.persist_directory))
        self._col = self._open_collection()

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> list[str]:
        """写入/覆盖一批文档，embeddings 必须由调用方提前算好。"""
        if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
            raise ValueError("ids/documents/embeddings/metadatas 数量必须一致")
        if not ids:
            return []
        self._col.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return ids

    def query(self, query_embeddings: list[list[float]], n_results: int) -> dict:
        """按向量查询，返回 Chroma 原始嵌套结果。"""
        if n_results <= 0:
            raise ValueError("n_results 必须大于 0")
        return self._col.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

    def count(self) -> int:
        return self._col.count()

    def reset(self) -> None:
        self._client.delete_collection(self.collection_name)
        self._col = self._open_collection()

    def _open_collection(self):
        return self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
