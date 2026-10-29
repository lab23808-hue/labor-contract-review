"""BM25Index：BM25Okapi（char_bigram 分词，k1=1.5，b=0.75）的纯内存索引。

只负责索引结构与打分/排序；对外的检索后端由 BM25Backend 提供。

算法与分词器沿用项目历史检索实验验证过的实现，保持与既有评测口径一致。

与实验脚本唯一的结构性差异：实验脚本里的 `_load_knowledge_documents_for_bm25()`
会先按 (source, article) 把同一条法条的多个 part 合并成一份完整法条再建索引
（那是为了"整条法条级别"的检索质量对比实验）；本模块按"单条 Evidence"
（即 KnowledgeLoader 已经切好的 chunk，与 Dense/Chroma 索引的粒度完全一致）为
一个 BM25 文档，不做合并——这是刻意的：生产环境下 Dense/BM25 两条路径返回给
LLM 的证据片段大小必须一致，否则切换策略会让引用体验忽然变化。

构建期显式校验（不静默降级，失败直接抛 BM25IndexBuildError，由上层
api/dependencies.py::build_app_state() 不捕获地往外抛，走 fail-fast）：
    - 知识库为空
    - 存在内容为空/全是空白的条目
    - 存在 (source, article, part, content) 完全相同的重复条目——复用
      `KnowledgeLoader._evidence_id()` 的同一套哈希算法判重，保证判重口径与
      Dense 路径写入 Chroma 时的去重口径一致，不是另起一套规则；只按内容哈希
      判重，不把"文本相似"等同于"重复"。
"""

import math
import statistics
from typing import Callable

from langchain_core.documents import Document

from retrieval.knowledge_loader import KnowledgeLoader
from core import Evidence

# 这条路径返回的 Evidence 相关性分数来自 BM25 原始分数（越大越相关），和
# ChromaVectorStore 返回的向量距离（通常越小越相关）在数值量级和含义上都不是
#一回事，不能直接比大小。已检查 prompts/review.py、retrieval/retriever.py，当前
# 生产代码里没有任何地方对 Evidence.metadata["score"] 做跨策略的数值比较，
# 所以这里只需要把语义标记出来，供以后任何想用这个分数做比较/排序/阈值判断的
# 代码先检查这个标记，不是说现在就存在真正的冲突需要修复。
SCORE_TYPE = "bm25_okapi_char_bigram"


class BM25IndexBuildError(Exception):
    """BM25 索引构建失败（空知识库、无效条文、重复条目等）。

    刻意不提供"构建失败就静默降级到 Dense"的逻辑——按本次接入的决定，构建失败
    必须让应用启动直接失败（fail fast），不能带着一个坏索引对外提供服务。
    """


def char_bigram_tokenizer(text: str) -> list[str]:
    """字符二元组分词器：过滤空白字符后，把相邻两个字符配成一个长度为 2 的 token。

    沿用项目历史检索实验中验证过的 char-bigram 实现；这也是
    ART26_WORKPLACE_RELOCATION_DIAGNOSIS 这个已知诊断案例里用来证实"零字符
    二元组重合"结论所用的同一个算法。
    """
    chars = [c for c in text if not c.isspace()]
    if len(chars) <= 1:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


class BM25Index:
    """BM25Okapi（k1=1.5, b=0.75）法律知识检索索引，纯内存、纯标准库实现。

    对外暴露的检索方法 `similarity_search(query, k)` 与
    `ChromaVectorStore.similarity_search(query, k)` 的返回契约完全一致：
    一个按相关性从高到低排列、已经截断到 k 条的 `(Document, score)` 列表。
    """

    def __init__(
        self,
        evidences: list[Evidence],
        tokenize: Callable[[str], list[str]] = char_bigram_tokenizer,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if not evidences:
            raise BM25IndexBuildError(
                "BM25 索引构建失败：传入的 Evidence 列表为空"
                "（正式知识库目录下没有任何可用条文，或目录本身不存在/没有 .txt 文件）"
            )

        self.tokenize = tokenize
        self.k1 = k1
        self.b = b

        # ---- 校验 + 建立稳定的"文档 <-> 原文/来源"映射 ----
        seen_ids: dict[str, Evidence] = {}
        self._documents: list[Document] = []
        for evidence in evidences:
            if not evidence.content or not evidence.content.strip():
                raise BM25IndexBuildError(
                    "BM25 索引构建失败：发现内容为空/全是空白的条文（无效条文）："
                    f"source={evidence.source!r}, article={evidence.article!r}"
                )

            # 复用 KnowledgeLoader._evidence_id() 的同一套哈希算法（基于
            # (source, article, part, content) 的内容本身），保证这里"重复"的
            # 判定口径与 Dense 路径写入 Chroma 时的去重口径完全一致——不是
            # 另起一套判重规则。调用的是 KnowledgeLoader 里带下划线前缀的
            # staticmethod：Python 不做访问限制，这样调用是为了避免把同一个
            # 哈希公式在两个地方各写一遍、以后悄悄跑偏；已在本次接入报告的
            # "遗留风险/知识树建议"里记录为一个值得关注的小瑕疵（更干净的做法是
            # 把它从 KnowledgeLoader 的内部实现细节提升成一个独立的公开函数，
            # 但那属于改动 retrieval/knowledge_loader.py，超出本轮批准的改动范围）。
            evidence_id = KnowledgeLoader._evidence_id(evidence)
            if evidence_id in seen_ids:
                prior = seen_ids[evidence_id]
                raise BM25IndexBuildError(
                    "BM25 索引构建失败：发现重复条目——(source, article, part, content) "
                    f"完全相同（哈希 id={evidence_id}）。\n"
                    f"  已存在条目：source={prior.source!r}, article={prior.article!r}, "
                    f"part={prior.metadata.get('part', '')!r}\n"
                    f"  冲突条目：  source={evidence.source!r}, article={evidence.article!r}, "
                    f"part={evidence.metadata.get('part', '')!r}\n"
                    "注意：这里判重只看内容哈希（同一来源 + 同一条号 + 同一分片编号 + 逐字相同的正文），"
                    "两条内容相近但不完全相同的条文不会被判定为重复。"
                )
            seen_ids[evidence_id] = evidence

            metadata = KnowledgeLoader._to_metadata(evidence)
            metadata["score_type"] = SCORE_TYPE
            self._documents.append(Document(page_content=evidence.content, metadata=metadata))

        self.doc_tokens: list[list[str]] = [tokenize(d.page_content) for d in self._documents]
        self.doc_lens: list[int] = [len(toks) for toks in self.doc_tokens]
        self.avgdl: float = statistics.mean(self.doc_lens) if self.doc_lens else 0.0
        self.N: int = len(self._documents)

        self.df: dict[str, int] = {}
        self.doc_tf: list[dict[str, int]] = []
        for toks in self.doc_tokens:
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self.doc_tf.append(tf)
            for t in tf:
                self.df[t] = self.df.get(t, 0) + 1
        self.idf: dict[str, float] = {
            t: math.log((self.N - df + 0.5) / (df + 0.5) + 1.0) for t, df in self.df.items()
        }

    def similarity_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        """BM25Okapi 检索，返回按相关性从高到低排列、截断到 k 条的 (Document, score)。

        与 ChromaVectorStore.similarity_search 的返回契约一致，
        retrieval/retriever.py 的调用方代码不需要知道背后是哪一种实现。

        score 含义：BM25 原始分数，越大越相关；与 Chroma 的向量距离不是同一个
        量级/含义，不能直接比较数值大小（见模块顶部 SCORE_TYPE 的说明，以及每条
        结果 metadata["score_type"]）。
        """
        if k <= 0:
            raise ValueError("k 必须大于 0")

        q_tokens = self.tokenize(query)
        scores = [0.0] * self.N
        for i in range(self.N):
            tf = self.doc_tf[i]
            dl = self.doc_lens[i]
            denom_norm = self.k1 * (1 - self.b + self.b * (dl / self.avgdl if self.avgdl else 0))
            score = 0.0
            for t in q_tokens:
                if t not in tf:
                    continue
                idf = self.idf.get(t, 0.0)
                freq = tf[t]
                score += idf * (freq * (self.k1 + 1)) / (freq + denom_norm)
            scores[i] = score

        order = sorted(range(self.N), key=lambda i: (-scores[i], i))
        top = order[:k]
        return [(self._documents[i], scores[i]) for i in top]

    def count(self) -> int:
        """当前索引中的文档（Evidence chunk）数量——与
        ChromaVectorStore.count() 对齐，便于验收检查统一写法。"""
        return self.N
