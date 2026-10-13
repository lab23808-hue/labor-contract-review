"""ChromaKnowledgeBase：Chroma 向量数据库的连接与基础读写。

本文件是整个项目里唯一直接触碰 Chroma 的地方：创建/连接 collection、写入文档、
按向量检索、清空，全部封装在这里。存的是什么内容（法条、Evidence 等业务概念）
由 loader.py / retrieval.py 决定，本文件只管“连接和基础读写”。

Embedding 不是一个需要手动调用的步骤：写入（add_texts）和检索（similarity_search）
内部都会自动调用构造时传入的 embedding_function（由 embedding.py 构造），
这是 LangChain 向量库的标准用法。
"""

from pathlib import Path
from typing import Optional, Union

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from config import settings

# 默认持久化目录与 collection 名称：见 config/settings.py。
DEFAULT_PERSIST_DIR = settings.CHROMA_DIR
DEFAULT_COLLECTION_NAME = settings.CHROMA_COLLECTION_NAME


class ChromaKnowledgeBase:
    """对某个 Chroma collection 的连接。

    同一个 (persist_directory, collection_name) 组合在多次运行之间是持久化的
    （数据落盘），重新创建实例、甚至重启进程都不会丢数据。
    """

    def __init__(
        self,
        embedding_function: Embeddings,
        persist_directory: Union[str, Path, None] = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        self.embedding_function = embedding_function
        self.persist_directory = Path(persist_directory) if persist_directory is not None else DEFAULT_PERSIST_DIR
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._store = self._open_store()

    def add_texts(
        self, texts: list[str], metadatas: list[dict], ids: Optional[list[str]] = None
    ) -> list[str]:
        """写入文档（Chroma 内部会自动调用 embedding_function 生成向量）。返回写入后的文档 id 列表。"""
        if len(texts) != len(metadatas):
            raise ValueError("texts 和 metadatas 数量必须一致")
        if ids is not None and len(ids) != len(texts):
            raise ValueError("ids 和 texts 数量必须一致")
        if not texts:
            return []
        return self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)

    def similarity_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        """按向量相似度检索（Chroma 内部会自动调用 embedding_function 生成查询向量）。

        返回 (Document, 距离分数) 列表，按相似度从高到低排列；
        分数含义取决于 Chroma 的距离度量配置，本方法不对分数做二次加工。
        """
        if k <= 0:
            raise ValueError("k 必须大于 0")
        return self._store.similarity_search_with_score(query, k=k)

    def count(self) -> int:
        """当前 collection 中的文档数量。"""
        # langchain_chroma.Chroma 没有专门暴露“数量”的公开方法，
        # 这里借助其底层的 chromadb collection 对象；如果以后 langchain-chroma
        # 提供了官方的 count() 接口，应优先改用官方接口。
        return self._store._collection.count()

    def reset(self) -> None:
        """清空当前 collection 中的全部文档（用于重建知识库或测试清理）。"""
        self._store.delete_collection()
        self._store = self._open_store()

    def _open_store(self) -> Chroma:
        return Chroma(
            collection_name=self.collection_name,
            embedding_function=self.embedding_function,
            persist_directory=str(self.persist_directory),
        )
