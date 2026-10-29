"""DocumentParser：把上传的合同文件转换成“纯文本字符串”。

输出约定（与 ClauseSplitter 的输入一致）：
    parse_file() / parse_bytes() 返回一个 str，可以直接传给 ClauseSplitter.split(text)。

核心原则：不改动原文内容。
    Clause 的 start_char / end_char 是相对于“本模块返回的字符串”计算的，
    这个字符串就是整条流水线里的原文（前端展示、审计追踪都要用同一份）。
    所以这里只做“字节 → 字符串”的解码，不做 strip、不统一换行、不删空行、
    不做全角/半角替换。读文件用二进制方式，避免 Python 文本模式悄悄把 \\r\\n 改成 \\n。
    唯一被去掉的是编码层面的 BOM 标记：它不属于文本内容，
    而且留着会挡住首行“第一条”的行首匹配。

扩展方式（PDF / DOCX / OCR）：
    1. 继承 BaseParser，声明 suffixes，实现 parse_bytes(data) -> str
    2. DocumentParser().register(你的解析器)，或在 default_parsers() 里替换掉对应的占位类
    DocumentParser 按文件扩展名分发，其余代码不需要改。

本模块是纯函数式的解析能力：输入文件路径/字节，输出文本；不触碰
ContractManager，不接受 contract_id，不保存任何东西，也不调用其他业务服务。
谁来调用（上传 → 解析 → 保存）属于 workflows 层的编排，不在这里。
"""

import codecs
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Optional, Union


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class DocumentParseError(Exception):
    """文件无法被解析成文本（编码无法识别、内容为空等）。"""


class UnsupportedFormatError(DocumentParseError):
    """没有注册能处理该扩展名的解析器。"""


# ---------------------------------------------------------------------------
# 解析器接口
# ---------------------------------------------------------------------------

class BaseParser(ABC):
    """单一格式的解析器。输入是文件的原始字节，输出是原文字符串。

    以字节而不是路径作为输入，是为了让本地文件和 FastAPI 上传（内存中的 bytes）
    共用同一套逻辑，不需要先落盘成临时文件。
    """

    # 该解析器负责的扩展名（小写，带点），例如 (".txt",)
    suffixes: tuple[str, ...] = ()

    @abstractmethod
    def parse_bytes(self, data: bytes) -> str:
        """把文件字节转换成文本。不得修改文本内容（见模块说明）。"""


# ---------------------------------------------------------------------------
# txt（已实现）
# ---------------------------------------------------------------------------

# 带 BOM 的编码。注意 UTF-32 LE 的 BOM 以 UTF-16 LE 的 BOM 开头，所以 UTF-32 要先检查。
_BOM_ENCODINGS = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]

# 没有 BOM 时依次尝试。utf-8-sig 兼容“带 BOM 的 UTF-8”和普通 UTF-8；
# gb18030 是 GBK / GB2312 的超集，覆盖国内常见的 ANSI 保存的 txt。
# 顺序不能反：gb18030 能解码的字节序列很多，必须放在严格的 UTF-8 之后。
_FALLBACK_ENCODINGS = ("utf-8-sig", "gb18030")


class TxtParser(BaseParser):
    """纯文本解析器：只负责识别编码并解码。"""

    suffixes = (".txt",)

    def parse_bytes(self, data: bytes) -> str:
        return self.decode(data)[0]

    @staticmethod
    def decode(data: bytes) -> tuple[str, str]:
        """解码字节，返回 (文本, 使用的编码名)。"""
        for bom, encoding in _BOM_ENCODINGS:
            if data.startswith(bom):
                try:
                    return data.decode(encoding), encoding  # 该编码会自动去掉 BOM
                except UnicodeDecodeError as e:
                    raise DocumentParseError(f"文件带有 {encoding} 标记，但无法解码：{e}") from e

        # 没有 BOM 却含有空字节：基本是二进制文件（或没带 BOM 的 UTF-16），不要硬解码
        if b"\x00" in data:
            raise DocumentParseError("文件含有空字节，不像纯文本文件（可能是二进制文件）")

        for encoding in _FALLBACK_ENCODINGS:
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise DocumentParseError("无法识别文件编码（已尝试 UTF-8、GB18030）")


# ---------------------------------------------------------------------------
# 预留：PDF / DOCX / OCR（尚未实现）
# ---------------------------------------------------------------------------

class PdfParser(BaseParser):
    """预留：PDF 解析。文本型 PDF 计划直接提取文字；扫描件转交 OcrParser。"""

    suffixes = (".pdf",)

    def parse_bytes(self, data: bytes) -> str:
        raise NotImplementedError("PDF 解析尚未实现")


class DocxParser(BaseParser):
    """预留：Word (.docx) 解析。"""

    suffixes = (".docx",)

    def parse_bytes(self, data: bytes) -> str:
        raise NotImplementedError("DOCX 解析尚未实现")


class OcrParser(BaseParser):
    """预留：图片/扫描件 OCR。"""

    suffixes = (".png", ".jpg", ".jpeg", ".tif", ".tiff")

    def parse_bytes(self, data: bytes) -> str:
        raise NotImplementedError("OCR 解析尚未实现")


def default_parsers() -> list[BaseParser]:
    """默认注册的解析器。实现新格式后，把对应的占位类换成真实实现即可。"""
    return [TxtParser(), PdfParser(), DocxParser(), OcrParser()]


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

class DocumentParser:
    """按扩展名把文件分发给对应的解析器，返回可直接交给 ClauseSplitter 的原文字符串。

    用法：
        text = DocumentParser().parse_file("contract.txt")
        clauses = ClauseSplitter().split(text)

        # FastAPI 上传（内存字节）：
        text = DocumentParser().parse_bytes(await file.read(), file.filename)
    """

    def __init__(self, parsers: Optional[Iterable[BaseParser]] = None) -> None:
        self._by_suffix: dict[str, BaseParser] = {}
        for parser in default_parsers() if parsers is None else parsers:
            self.register(parser)

    def register(self, parser: BaseParser) -> None:
        """注册（或覆盖）某个解析器负责的扩展名。"""
        for suffix in parser.suffixes:
            self._by_suffix[suffix.lower()] = parser

    def parse_file(self, path: Union[str, Path]) -> str:
        """解析本地文件。文件不存在时抛出 FileNotFoundError。"""
        path = Path(path)
        return self.parse_bytes(path.read_bytes(), path.name)  # 二进制读取，不做换行转换

    def parse_bytes(self, data: bytes, filename: str) -> str:
        """解析内存中的文件内容。filename 只用来判断格式（取扩展名）。"""
        suffix = Path(filename).suffix.lower()
        parser = self._by_suffix.get(suffix)
        if parser is None:
            raise UnsupportedFormatError(
                f"不支持的文件格式：{suffix or '（无扩展名）'}；已注册：{sorted(self._by_suffix)}"
            )

        text = parser.parse_bytes(data)

        # 所有格式共用的检查：解析不出任何文字（空文件、纯图片 PDF 等）视为失败，
        # 而不是把空字符串悄悄传给后面的流程。这里只检查，不修改 text。
        if not text.strip():
            raise DocumentParseError("文件中没有可用的文本内容")
        return text
