"""schemas：整个系统的数据契约。

其他模块之间只允许传递这里定义的对象，不要传递随意格式的 dict。
本包不依赖项目里的任何其他模块。
"""

from schemas.clause import Clause
from schemas.contract import Contract, ContractStatus
from schemas.contract_version import ContractVersion
from schemas.diff import ClauseDiffEntry, RiskDiffEntry, RiskDiffResult
from schemas.evidence import Evidence
from schemas.modification_batch import ModificationBatch, ModificationBatchStatus
from schemas.modification_result import ModificationResult
from schemas.modification_task import (
    MAX_MODIFICATION_ATTEMPTS,
    ModificationAttempt,
    ModificationTask,
    ModificationTaskStatus,
    ReviewResultSnapshot,
    RiskResolution,
)
from schemas.review_record import ReviewRecord
from schemas.review_report import FailedClause, ReviewReport, ReviewVersions, RiskSummary
from schemas.review_result import RISK_LEVEL_LABELS_ZH, ReviewResult, ReviewSource, RiskLevel
from schemas.validation_result import ValidationResult

__all__ = [
    "Clause",
    "Evidence",
    "Contract",
    "ContractStatus",
    "ReviewResult",
    "ReviewSource",
    "RiskLevel",
    "RISK_LEVEL_LABELS_ZH",
    "ReviewReport",
    "RiskSummary",
    "FailedClause",
    "ReviewVersions",
    "ReviewRecord",
    "ModificationTask",
    "ModificationTaskStatus",
    "ModificationAttempt",
    "ReviewResultSnapshot",
    "RiskResolution",
    "MAX_MODIFICATION_ATTEMPTS",
    "ModificationBatch",
    "ModificationBatchStatus",
    "ModificationResult",
    "ValidationResult",
    "ContractVersion",
    "ClauseDiffEntry",
    "RiskDiffEntry",
    "RiskDiffResult",
]
