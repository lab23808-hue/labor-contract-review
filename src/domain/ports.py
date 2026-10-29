"""领域层依赖的端口（Protocol）。

领域层只依赖这些抽象；具体实现由 infra 提供，在组合根注入。
"""

from pathlib import Path
from typing import Any, Optional, Protocol, Union

from core import (
    Clause,
    ModificationBatch,
    ModificationTask,
    ReviewRecord,
    ReviewResultSnapshot,
)


class PortError(Exception):
    """端口层错误的基类。"""


class StorageError(PortError):
    """存储实现返回的业务错误。"""


class StorageNotFoundError(StorageError):
    """存储对象不存在。"""


class LLMPortError(PortError):
    """LLM 调用失败。"""


class LLMPort(Protocol):
    def chat(self, messages: list[dict], *, json_mode: bool = False) -> str: ...

    def chat_with_tool(self, messages: list[dict], tool_schema: dict, temperature: float = 0.0) -> dict: ...


class StoragePort(Protocol):
    def get_original_file_path(self, contract_id: str) -> Path: ...

    def get_parsed_text(self, contract_id: str) -> str: ...

    def save_parsed_text(self, contract_id: str, text: str) -> Path: ...

    def save_clauses(self, contract_id: str, clauses: list[Clause]) -> Path: ...

    def load_clauses(self, contract_id: str) -> Optional[list[Clause]]: ...

    def get_clauses(self, contract_id: str) -> list[Clause]: ...

    def get_review(self, contract_id: str, review_id: str) -> ReviewRecord: ...

    def get_batch(self, contract_id: str, batch_id: str) -> ModificationBatch: ...

    def create_batch(self, contract_id: str, source_review_id: str) -> ModificationBatch: ...

    def update_batch(self, batch: ModificationBatch) -> ModificationBatch: ...

    def create_modification_task(
        self,
        contract_id: str,
        clause_id: str,
        original_text: str,
        lawyer_instruction: str,
        batch_id: str,
        source_review_id: str,
        source_review_snapshot: ReviewResultSnapshot,
    ) -> ModificationTask: ...

    def list_modification_tasks(self, contract_id: str) -> list[ModificationTask]: ...

    def get_modification_task(self, contract_id: str, task_id: str) -> ModificationTask: ...

    def update_modification_task(self, task: ModificationTask) -> ModificationTask: ...
