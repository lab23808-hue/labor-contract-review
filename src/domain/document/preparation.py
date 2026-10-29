"""Contract Preparation：合同"解析 → 保存 → 切分 → 保存"编排能力。

这是一个 Capability 层模块（架构分层：API → Application/Workflow →
Capability → Infrastructure/Storage）：向下调用 document.parser /
document.splitter（纯函数能力）+ contract.ContractManager（Storage），
向上被 workflows.review_workflow（Review Workflow 的 Contract Loading
节点）、modification.service（generate_v2 对 V2 全文重新走一遍同样的流程）、
api/routes/contracts.py（POST /parse 路由）三个调用方共用。

本次（Stage 2）架构重构前，这段编排逻辑写在 workflows/review_workflow.py
里，被 review_workflow 自己、api/routes/contracts.py、modification/service.py
三处分别 import——Review Workflow 因此变成了"其他模块伸手进来拿一个工具函数"
的地方，这不是它该扮演的角色（Review Workflow 只应该编排"一次完整合同审查"
这一件事）。现在把它独立成 document 包下的一个 Capability 模块：document
包本来就是"文本处理能力"的家（parser.py / splitter.py / reconstructor.py），
parse_contract/split_contract 是"parser 和 splitter 各自接上 ContractManager
持久化"这一层编排，放在 document 包里符合既有命名习惯，也让 document 包
从"纯函数集合"自然升级为"纯函数 + 面向 ContractManager 的编排"，不需要新建
一个单独的顶层包。

contract_loading / generate_v2 / POST /parse 现在都只应该调用
parse_and_split_contract（或 parse_contract / split_contract），不应该
再各自知道"先解析再切分、各自存一次"这几步的顺序——这件事只在这里写一次。
"""

from typing import Optional

from domain.ports import StoragePort
from domain.document.parser import DocumentParser
from domain.document.splitter import ClauseSplitter
from core import Clause


def parse_contract(
    contract_id: str,
    contract_manager: StoragePort,
    document_parser: Optional[DocumentParser] = None,
) -> str:
    """解析某份已上传的合同，并把结果保存回它的合同目录。返回解析出的文本。

    contract_manager 负责定位原始文件、保存解析结果；document_parser
    （document.parser.DocumentParser）只负责"文件字节 → 文本"，不知道
    contract_id 的存在。
    """
    document_parser = document_parser or DocumentParser()
    original_path = contract_manager.get_original_file_path(contract_id)
    text = document_parser.parse_file(original_path)
    contract_manager.save_parsed_text(contract_id, text)
    return text


def split_contract(
    contract_id: str,
    contract_manager: StoragePort,
    clause_splitter: Optional[ClauseSplitter] = None,
) -> list[Clause]:
    """切分某份已解析的合同，并把结果保存回它的合同目录。返回 Clause 列表。

    contract_manager 负责提供原文、保存切分结果；clause_splitter
    （document.splitter.ClauseSplitter）只负责"文本 → Clause 列表"，不知道
    contract_id 该存到哪里（它需要 contract_id 只是为了把这个值写进每个
    Clause，作为数据本身的一部分）。
    """
    clause_splitter = clause_splitter or ClauseSplitter()
    text = contract_manager.get_parsed_text(contract_id)
    clauses = clause_splitter.split(text, contract_id)
    contract_manager.save_clauses(contract_id, clauses)
    return clauses


def parse_and_split_contract(
    contract_id: str,
    contract_manager: StoragePort,
    document_parser: Optional[DocumentParser] = None,
    clause_splitter: Optional[ClauseSplitter] = None,
) -> list[Clause]:
    """合同加载编排：parse_contract + split_contract 的组合，一步完成
    "解析 → 保存 → 切分 → 保存"。

    调用方：
        - workflows.review_workflow 的 Contract Loading 节点（V1、V2 都走
          这同一个节点，它不知道、也不需要知道自己在处理的是 V1 还是 V2）；
        - modification.service.ModificationService.generate_v2（V2 全文
          重建完成后，重新走一遍同样的解析 + 切分流程）；
        - api/routes/contracts.py 的 POST /{contract_id}/parse 路由。
    """
    parse_contract(contract_id, contract_manager, document_parser)
    return split_contract(contract_id, contract_manager, clause_splitter)
