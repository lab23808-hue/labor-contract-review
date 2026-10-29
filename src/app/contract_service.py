"""合同读取/入库用例服务。

API 路由只通过本服务访问合同数据，不再直接依赖 ContractManager。
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from core import Clause, Contract, ModificationBatch, ModificationTask, ReviewRecord
from domain.document.preparation import parse_and_split_contract
from infra.storage import ContractManager


class ContractApplicationService:
    def __init__(self, contract_manager: ContractManager) -> None:
        self.contract_manager = contract_manager

    def list_contracts(self, exclude_version_hosts: bool = True) -> list[Contract]:
        return self.contract_manager.list_contracts(exclude_version_hosts=exclude_version_hosts)

    def create_contract(self, path: Union[str, Path]) -> Contract:
        return self.contract_manager.create_contract(path)

    def parse_and_split(self, contract_id: str) -> list[Clause]:
        return parse_and_split_contract(contract_id, self.contract_manager)

    def get_contract(self, contract_id: str) -> Contract:
        return self.contract_manager.get_contract(contract_id)

    def get_clauses(self, contract_id: str) -> list[Clause]:
        return self.contract_manager.get_clauses(contract_id)

    def get_text(self, contract_id: str) -> str:
        self.contract_manager.get_contract(contract_id)
        return self.contract_manager.get_parsed_text(contract_id)

    def get_latest_review(self, contract_id: str) -> ReviewRecord:
        return self.contract_manager.get_latest_review(contract_id)

    def list_reviews(self, contract_id: str) -> list[ReviewRecord]:
        return self.contract_manager.list_reviews(contract_id)

    def list_modification_tasks(self, contract_id: str) -> list[ModificationTask]:
        return self.contract_manager.list_modification_tasks(contract_id)

    def list_batches(self, contract_id: str) -> list[ModificationBatch]:
        return self.contract_manager.list_batches(contract_id)

    def get_batch(self, contract_id: str, batch_id: str) -> ModificationBatch:
        return self.contract_manager.get_batch(contract_id, batch_id)

    def list_versions(self, contract_id: str):
        return self.contract_manager.list_versions(contract_id)
