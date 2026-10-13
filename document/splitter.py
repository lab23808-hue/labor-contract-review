"""ClauseSplitter：把合同全文切分成结构化的 Clause 列表。

切分分两个阶段：

1. 结构切分（正则）：先按“第X条”切出每一条，再在条内按款的编号
   （1. / （一） / （1））切出每一款，并建立 parent_clause 关系。
   原因：RecursiveCharacterTextSplitter 会把相邻的小片段合并到 chunk_size，
   如果只靠它，几个很短的条会被合并进同一个 chunk，条款边界就丢了。

2. 长度控制（RecursiveCharacterTextSplitter）：只有超过 chunk_size 的过长条款，
   才用 RecursiveCharacterTextSplitter 按“换行 → 句号”继续切，尽量不在句子中间断开。

重要不变量（前端定位、审计追踪都依赖它）：
    对每个 clause，都有 full_text[clause.start_char:clause.end_char] == clause.original_text
所以本模块不会修改原文（不做任何替换/规范化）。换行符统一等预处理，应放在 DocumentParser。
"""

import re
from typing import Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from schemas import Clause

# ---------------------------------------------------------------------------
# 正则
# ---------------------------------------------------------------------------

_CN_DIGITS = "一二三四五六七八九十百千零〇两"
_INDENT = r"^[ \t\u3000]*"  # 行首允许的缩进（含全角空格）

# 条标题：行首的“第X条”。
# (?!的) 用来排除被换行断开的引用，例如“……依照\n第三十九条的规定”。
_ARTICLE_PATTERN = rf"第[{_CN_DIGITS}\d]+条"
_ARTICLE_RE = re.compile(rf"{_INDENT}({_ARTICLE_PATTERN})(?!的)", re.MULTILINE)

# 款的编号样式（都要求在行首）。
# 一个条内只采用“最先出现”的那种样式，其余样式视为嵌套内容，留在所属款里，
# 这样“（一）”下面再嵌套的“1.”不会被误切成同级。
_ITEM_STYLES = [
    re.compile(rf"{_INDENT}\d+[.．、](?!\d)", re.MULTILINE),           # 1.  1、  （不匹配 1.5）
    re.compile(rf"{_INDENT}[（(][{_CN_DIGITS}]+[）)]", re.MULTILINE),  # （一）
    re.compile(rf"{_INDENT}[（(]\d+[）)]", re.MULTILINE),              # （1）
]

# RecursiveCharacterTextSplitter 的分隔符（按优先级）：第X条 > 数字编号 > 换行 > 句号 > 逐字。
# 都用正则；“句号”用后行断言 (?<=...)，这样标点会留在前一句末尾。
_SEPARATORS = [
    rf"\n(?={_ARTICLE_PATTERN})",
    r"\n(?=\d+[.．、](?!\d))",
    r"\n",
    r"(?<=[。；])",
    "",  # 兜底：实在没有可切的地方，才逐字硬切
]


class ClauseSplitter:
    """合同条款切分器。

    chunk_size / chunk_overlap 只作用于“过长条款”的二次切分：

    - chunk_size=500（字符数）：中文合同的一条/一款通常在 50~400 字，500 能让绝大多数
      条款保持完整、不被切开；同时一段文字不至于长到让检索 query 和 LLM 提示变得含糊。
    - chunk_overlap=50：一个过长条款被切成多段时，相邻段重叠约一句话，避免后一段
      因缺少上文（如“该费用”“上述情形”）而失去指代。条款之间（正常结构切分）不重叠。

    这两个值的默认值来自 config/settings.py（CLAUSE_CHUNK_SIZE / CLAUSE_CHUNK_OVERLAP），
    仍然可以通过构造参数覆盖。
    """

    def __init__(
        self,
        chunk_size: int = settings.CLAUSE_CHUNK_SIZE,
        chunk_overlap: int = settings.CLAUSE_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap 必须满足 0 <= chunk_overlap < chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=_SEPARATORS,
            is_separator_regex=True,
            keep_separator="end",  # 分隔符保留，保证每个 chunk 都是原文的子串
            strip_whitespace=True,
        )

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def split(self, text: str, contract_id: str) -> list[Clause]:
        """把合同全文切成 Clause 列表（按原文顺序）。

        contract_id 会写入每个 Clause，标明它属于哪份合同。

        clause_id 规则：
            clause_000        第一条之前的前言（甲乙双方信息等），clause_type="preamble"
            clause_001        第 1 个条（按出现顺序编号，不是条文里的数字，避免重复编号时冲突）
            clause_001_2      第 1 个条下的第 2 款
            clause_001_p2     过长条款被二次切分后的第 2 段（款的形式：clause_001_2_p2）
        """
        if not text.strip():
            return []

        spans = self._find_article_spans(text)

        # 没有任何“第X条”：退化为整段文本交给长度控制
        if not spans:
            return self._build(
                text, contract_id, 0, len(text), "clause_001", 0, None, {"structure": "none"}
            )

        clauses: list[Clause] = []

        # 第一条之前的内容（前言）
        if spans[0][0] > 0:
            clauses += self._build(
                text, contract_id, 0, spans[0][0], "clause_000", 0, None, {}, clause_type="preamble"
            )

        for n, (start, end) in enumerate(spans, start=1):
            clauses += self._split_article(text, contract_id, n, start, end)
        return clauses

    # ------------------------------------------------------------------
    # 阶段 1：结构切分
    # ------------------------------------------------------------------

    @staticmethod
    def _find_article_spans(text: str) -> list[tuple[int, int]]:
        """返回每一条在全文中的 (start, end)。一条从它的标题行开始，到下一条标题行之前结束。"""
        starts = [m.start() for m in _ARTICLE_RE.finditer(text)]
        ends = starts[1:] + [len(text)]
        return list(zip(starts, ends))

    @staticmethod
    def _find_item_offsets(block: str) -> list[int]:
        """在一个条的文本里找出各款的起始偏移（相对 block）。只采用最先出现的编号样式。"""
        best: Optional[list[int]] = None
        for style in _ITEM_STYLES:
            offsets = [m.start() for m in style.finditer(block)]
            if offsets and (best is None or offsets[0] < best[0]):
                best = offsets
        return best or []

    def _split_article(
        self, text: str, contract_id: str, n: int, start: int, end: int
    ) -> list[Clause]:
        article_id = f"clause_{n:03d}"
        block = text[start:end]

        article_no = _ARTICLE_RE.match(block).group(1)  # 例如“第三条”
        heading = block.strip().split("\n", 1)[0].strip()  # 标题行，例如“第三条 工作地点”
        meta = {"article_no": article_no, "article_title": heading}

        offsets = self._find_item_offsets(block)

        # 没有款：整条就是一个 Clause（标题和正文写在同一行的情况也走这里）
        if not offsets:
            return self._build(text, contract_id, start, end, article_id, 0, None, meta)

        # 有款：条的“引导部分”（标题，以及第一款之前的文字）为第 0 层，每款为第 1 层。
        # 各 Clause 的范围互不重叠，合起来覆盖整条原文。
        clauses = self._build(
            text, contract_id, start, start + offsets[0], article_id, 0, None, meta
        )
        bounds = offsets + [len(block)]
        for k in range(len(offsets)):
            clauses += self._build(
                text,
                contract_id,
                start + bounds[k],
                start + bounds[k + 1],
                f"{article_id}_{k + 1}",
                1,
                article_id,
                meta,
            )
        return clauses

    # ------------------------------------------------------------------
    # 阶段 2：长度控制 + 构造 Clause
    # ------------------------------------------------------------------

    def _build(
        self,
        text: str,
        contract_id: str,
        start: int,
        end: int,
        clause_id: str,
        level: int,
        parent: Optional[str],
        meta: dict[str, Any],
        clause_type: str = "unknown",
    ) -> list[Clause]:
        """把 text[start:end] 变成 1 个或多个 Clause（过长则二次切分）。"""
        # 去掉首尾空白，并同步收紧偏移量，保证 text[start:end] == original_text
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start >= end:
            return []

        def make(cid: str, s: int, e: int, extra: dict[str, Any]) -> Clause:
            return Clause(
                contract_id=contract_id,
                clause_id=cid,
                clause_type=clause_type,
                original_text=text[s:e],
                page_number=None,  # txt 没有页码；PDF/DOCX 阶段再填
                start_char=s,
                end_char=e,
                parent_clause=parent,
                hierarchy_level=level,
                metadata={**meta, **extra},
            )

        if end - start <= self.chunk_size:
            return [make(clause_id, start, end, {})]

        # 过长：交给 RecursiveCharacterTextSplitter，再把每段定位回全文
        spans = self._locate_chunks(text[start:end], self._splitter.split_text(text[start:end]))
        if len(spans) <= 1:
            return [make(clause_id, start, end, {})]
        return [
            make(
                f"{clause_id}_p{j}",
                start + s,
                start + e,
                {"split_from": clause_id, "part": j, "parts": len(spans)},
            )
            for j, (s, e) in enumerate(spans, start=1)
        ]

    def _locate_chunks(self, body: str, chunks: list[str]) -> list[tuple[int, int]]:
        """找出每个 chunk 在 body 中的 (start, end)。

        RecursiveCharacterTextSplitter 只返回文本，不返回位置，所以需要自己定位。
        由于相邻 chunk 最多重叠 chunk_overlap 个字符，下一个 chunk 一定不会
        早于 “上一个的结尾 - chunk_overlap”，据此设置查找起点，避免文本重复时定位到更早的位置。
        找不到时直接报错，而不是悄悄给出错误的偏移量。
        """
        spans: list[tuple[int, int]] = []
        prev_start, prev_end = -1, 0
        for chunk in chunks:
            lower = max(prev_start + 1, prev_end - self.chunk_overlap, 0)
            pos = body.find(chunk, lower)
            if pos == -1:
                raise RuntimeError(f"无法在原文中定位切分出的片段：{chunk[:30]!r}")
            spans.append((pos, pos + len(chunk)))
            prev_start, prev_end = pos, pos + len(chunk)
        return spans
