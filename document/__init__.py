"""document：合同文本处理能力（Parser / Splitter / Reconstructor / Preparation）。

parser.py / splitter.py / reconstructor.py 三个文件是纯函数式的能力模块，
互相独立、都不触碰 ContractManager，也不知道 contract_id、
ModificationService 的存在：
    parser.py         文件/字节 → 原文字符串
    splitter.py        原文字符串 → 结构化 Clause 列表
    reconstructor.py   V1 原文 + 已确认的修改结果 → V2 全文

preparation.py 是本包里唯一知道 ContractManager（Storage）的模块：它把
parser.py / splitter.py 接上 ContractManager 的持久化，提供
parse_contract/split_contract/parse_and_split_contract 这组"解析 → 保存 →
切分 → 保存"的编排能力，供 workflows.review_workflow（Contract Loading
节点）、modification.service（generate_v2）、api/routes/contracts.py
（POST /parse）共用——这是一个 Capability 层模块，依赖 Storage（向下依赖）
是允许的；谁来调用它、什么时候调用，仍然是各自调用方自己的事，本包不处理。
"""

from document.parser import (
    BaseParser,
    DocumentParseError,
    DocumentParser,
    DocxParser,
    OcrParser,
    PdfParser,
    TxtParser,
    UnsupportedFormatError,
    default_parsers,
)
from document.preparation import parse_and_split_contract, parse_contract, split_contract
from document.splitter import ClauseSplitter

__all__ = [
    "DocumentParser",
    "BaseParser",
    "TxtParser",
    "PdfParser",
    "DocxParser",
    "OcrParser",
    "default_parsers",
    "DocumentParseError",
    "UnsupportedFormatError",
    "ClauseSplitter",
    "parse_contract",
    "split_contract",
    "parse_and_split_contract",
]
