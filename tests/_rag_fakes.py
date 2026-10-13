"""RAG 测试用的共享测试替身（不是 pytest 用例文件，pytest 不会收集它）。

FakeEmbeddings 是一个确定性的“伪嵌入”：按字符哈希做词袋向量，
只用来验证“切分 → 写入 → 检索 → 转换成 Evidence”这条管道的逻辑是否正确
（数据有没有传对、有没有丢），不代表真实的语义效果。
真实的检索质量必须用真正的 BGE-M3 模型在本地环境验证。
"""

import math

from langchain_core.embeddings import Embeddings

_DIM = 64


def _vector(text: str) -> list[float]:
    v = [0.0] * _DIM
    chars = text or " "
    for a, b in zip(chars, chars[1:] + chars[:1]):
        v[(ord(a) * 31 + ord(b)) % _DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class FakeEmbeddings(Embeddings):
    """记录每次调用的参数，方便测试断言“确实调用了 embedding”。"""

    def __init__(self) -> None:
        self.embed_documents_calls: list[list[str]] = []
        self.embed_query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls.append(list(texts))
        return [_vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls.append(text)
        return _vector(text)
