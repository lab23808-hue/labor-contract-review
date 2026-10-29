"""KnowledgeLoader：把法律文本切分成 Evidence，并写入 Chroma。

数据流：
    法律文本文件 → 按“第X条”切分 → 每条法条一个 Evidence → 写入 VectorSink

切分策略（刻意不依赖 clause.ClauseSplitter，见模块顶部架构要求）：
    法律文本本身就是逐条罗列的（“第X条 ……”），按条切分后，
    检索出来的每条依据都是完整、有明确条号的一条法律条文，不会是半句话。
    只有极少数超长条文才用 RecursiveCharacterTextSplitter 按“换行 → 句号”二次切分。
    这与 clause 包里 ClauseSplitter 的两阶段思路一致，但这里是独立、更简单的实现：
    法律条文一般不需要处理款/项的嵌套层级，所以没有那一层结构。
"""

import hashlib
import re
from pathlib import Path
from typing import Optional, Union

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from retrieval.base import VectorSink
from core import Evidence

_CN_DIGITS = "一二三四五六七八九十百千零〇两"
_INDENT = r"^[ \t\u3000]*"

# 条标题：行首的“第X条”。(?!的) 排除被换行断开的引用，例如“……依照\n第三十九条的规定”。
_ARTICLE_RE = re.compile(rf"{_INDENT}(第[{_CN_DIGITS}\d]+条)(?!的)", re.MULTILINE)

# 只有换行、句末标点、逐字兜底三级，不含“数字编号”这一级（法条内部不处理款/项）。
_SEPARATORS = [r"\n", r"(?<=[。；])", ""]


def load_version(version_file: Optional[Union[str, Path]] = None) -> str:
    """读取知识库 VERSION；文件缺失或为空时返回 "unknown"。"""
    path = Path(version_file) if version_file is not None else settings.KNOWLEDGE_DIR / "VERSION"
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return content or "unknown"


class KnowledgeLoader:
    """法律知识入库器。

    chunk_size / chunk_overlap 的含义和默认值与 clause.ClauseSplitter 一致：
    只作用于“超过长度限制的单条法条”的二次切分，绝大多数法条长度都在限制之内，
    不会被二次切分。
    """

    def __init__(
        self,
        knowledge_base: Optional[VectorSink],
        chunk_size: int = settings.KNOWLEDGE_CHUNK_SIZE,
        chunk_overlap: int = settings.KNOWLEDGE_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap 必须满足 0 <= chunk_overlap < chunk_size")
        self.knowledge_base = knowledge_base
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=_SEPARATORS,
            is_separator_regex=True,
            keep_separator="end",
            strip_whitespace=True,
        )

    # ------------------------------------------------------------------
    # 切分（纯函数，不写入数据库，便于单独测试）
    # ------------------------------------------------------------------

    def split_text(self, text: str, source: str) -> list[Evidence]:
        """把一份法律文本切成 Evidence 列表。"""
        spans = self._find_article_spans(text)
        if not spans:
            # 没有任何“第X条”：整份文本当成一份没有条号的资料
            return self._build(text, source, None)

        evidences: list[Evidence] = []
        for start, end in spans:
            block = text[start:end].strip()
            if not block:
                continue
            article_no = _ARTICLE_RE.match(block).group(1)
            evidences += self._build(block, source, article_no)
        return evidences

    def _find_article_spans(self, text: str) -> list[tuple[int, int]]:
        starts = [m.start() for m in _ARTICLE_RE.finditer(text)]
        ends = starts[1:] + [len(text)]
        return list(zip(starts, ends))

    def _build(self, block: str, source: str, article: Optional[str]) -> list[Evidence]:
        block = block.strip()
        if not block:
            return []
        if len(block) <= self.chunk_size:
            return [Evidence(content=block, source=source, article=article, metadata={})]

        parts = self._splitter.split_text(block)
        if len(parts) <= 1:
            return [Evidence(content=block, source=source, article=article, metadata={})]
        return [
            Evidence(
                content=part,
                source=source,
                article=article,
                metadata={"part": i, "parts": len(parts)},
            )
            for i, part in enumerate(parts, start=1)
        ]

    # ------------------------------------------------------------------
    # 读文件 / 目录
    # ------------------------------------------------------------------

    def load_file(self, path: Union[str, Path], source: Optional[str] = None) -> list[Evidence]:
        """读取单个法律文本文件（.txt，utf-8），切分成 Evidence。不写入数据库。

        source 默认取文件名（不含扩展名），例如 "劳动合同法.txt" → source="劳动合同法"。
        """
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        return self.split_text(text, source or path.stem)

    def load_directory(self, dir_path: Union[str, Path]) -> list[Evidence]:
        """读取目录下所有 .txt 文件，切分成 Evidence（按文件名排序，不写入数据库）。"""
        dir_path = Path(dir_path)
        evidences: list[Evidence] = []
        for file in sorted(dir_path.glob("*.txt")):
            evidences += self.load_file(file)
        return evidences

    def count_evidences(self, dir_path: Union[str, Path]) -> int:
        """只复用切分逻辑统计 Evidence 数量，不做 embedding、不写索引。"""
        return len(self.load_directory(dir_path))

    # ------------------------------------------------------------------
    # 写入数据库
    # ------------------------------------------------------------------

    def index(self, evidences: list[Evidence]) -> list[str]:
        """把 Evidence 列表写入向量后端，返回写入后的文档 id 列表。

        id 由 `_evidence_id()` 从 (source, article, part, content) 确定性生成；
        相同内容重复 index 会命中同一个 id，由 ChromaVectorStore.upsert 覆盖。
        同一批内若出现完全相同的 id，则按 id 保留第一条，避免 chromadb 的
        批内 DuplicateIDError。
        """
        if not evidences:
            return []
        ids = [self._evidence_id(e) for e in evidences]
        texts = [e.content for e in evidences]
        metadatas = [self._to_metadata(e) for e in evidences]

        # 批内去重：同一次调用里如果出现了 id 完全相同的条目（无论是因为内容真的
        # 逐字重复，还是调用方意外传入了重复的 Evidence），按 id 保留第一条出现的，
        # 丢弃后面重复的——而不是把重复的 id 原样传给 add_texts（会被 chromadb 拒绝），
        # 也不是给它们现造一个随机 id（会破坏幂等性，见上面的 docstring）。
        seen: set[str] = set()
        dedup_ids: list[str] = []
        dedup_texts: list[str] = []
        dedup_metadatas: list[dict] = []
        for id_, text, metadata in zip(ids, texts, metadatas):
            if id_ in seen:
                continue
            seen.add(id_)
            dedup_ids.append(id_)
            dedup_texts.append(text)
            dedup_metadatas.append(metadata)

        return self.knowledge_base.add_texts(dedup_texts, dedup_metadatas, ids=dedup_ids)

    @staticmethod
    def _evidence_id(evidence: Evidence) -> str:
        """从 Evidence 的内容本身确定性地算出一个 id：相同的
        (source, article, part, content) 永远得到相同的 id，不同的内容（哪怕只差
        一个字）得到不同的 id——这是让 `index()` 具备"重复调用不产生重复数据"这个
        幂等性的基础，具体原理见 `index()` 的 docstring。

        **2026-10-10 追加 `part`（本轮修复，见 `index()` docstring 里的详细说明）**：
        原来的实现不把 `metadata` 里的 `part` 纳入 id 计算，理由是"同一次切分里不会
        有两个片段的 (source, article, content) 完全相同"——这个假设被真实场景打破了：
        一条超长法条如果内容高度重复（比如同一句话连续出现多次），二次切分出来的多个
        part 可能逐字相同，这时如果不区分 part，就会算出相同的 id，同一批写入时
        被 chromadb 判定为"批内 id 重复"而报错。现在把 `metadata.get("part")`
        （没有二次切分的 Evidence 没有这个字段，取不到就是空字符串，等价于原来的
        行为）纳入哈希输入，用"这是第几片"这个位置信息区分内容相同的片段。

        这不影响跨批次的幂等性：只要切分参数（chunk_size/chunk_overlap）不变，
        `RecursiveCharacterTextSplitter` 对同一段文本的切分结果是确定性的，同一个
        part 序号对应的 content 每次重新切分都一样，id 也就每次都一样，重复索引
        仍然会命中同一批 id 走 upsert，不会重复计数。

        纳入 `part` 之后，"同一条法条用不同 chunk_size 重新索引、旧的 part 不会被
        自动清理"这个限制（见 `tests/test_rag_loader.py` 里的
        `test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset`）
        没有变化，本轮也没有尝试解决它——这是 upsert 天然做不到的事（它不知道"哪些
        旧 id 现在不该存在了"），留作已知、已被测试显式钉住的限制，不是本轮修复范围。
        """
        part = evidence.metadata.get("part", "")
        raw = f"{evidence.source}\x00{evidence.article or ''}\x00{part}\x00{evidence.content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def load_and_index_file(self, path: Union[str, Path], source: Optional[str] = None) -> list[Evidence]:
        """load_file + index 的组合，一步完成“读文件 → 写入数据库”。"""
        evidences = self.load_file(path, source)
        self.index(evidences)
        return evidences

    def load_and_index_directory(self, dir_path: Union[str, Path]) -> list[Evidence]:
        """load_directory + index 的组合。"""
        evidences = self.load_directory(dir_path)
        self.index(evidences)
        return evidences

    @staticmethod
    def _to_metadata(evidence: Evidence) -> dict:
        # Chroma 的 metadata 只能存字符串/数字/布尔，不能是 None，
        # 所以 article 为 None 时直接不写这个键，而不是写 article=None。
        meta = {"source": evidence.source, **evidence.metadata}
        if evidence.article is not None:
            meta["article"] = evidence.article
        return meta
