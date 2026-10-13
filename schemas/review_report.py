"""一份合同的完整审查报告（pipeline 的最终产出，formatter 的输入）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field, field_validator

from schemas._time import require_aware, utc_now
from schemas.review_result import ReviewResult, RiskLevel


class RiskSummary(BaseModel):
    """各风险等级的结果数量。"""

    high: int = 0
    medium: int = 0
    low: int = 0
    none: int = 0


class FailedClause(BaseModel):
    """审查失败的条款（例如 LLM 超时、输出格式不合法且重试仍失败）。"""

    clause_id: str = Field(..., min_length=1)
    error: str


class ReviewVersions(BaseModel):
    """生成这份报告时用到的各组件版本，便于复现和追责。

    各项都可选：对应模块尚未接入时为 None。
    """

    llm_model: Optional[str] = None
    prompt_version: Optional[str] = None
    ruleset_version: Optional[str] = None
    knowledge_base_version: Optional[str] = None


class ReviewReport(BaseModel):
    """审查报告。

    summary 和 overall_risk_level 由 results 自动计算，不单独存储，避免与明细不一致。
    注意：某些条款审查失败时，它们不在 results 里；使用报告前应同时检查 failed_clauses，
    只看 overall_risk_level 可能低估风险。
    """

    contract_id: str = Field(..., min_length=1)
    generated_at: datetime = Field(default_factory=utc_now)
    results: list[ReviewResult] = Field(default_factory=list)
    failed_clauses: list[FailedClause] = Field(default_factory=list)
    versions: ReviewVersions = Field(default_factory=ReviewVersions)

    @field_validator("generated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return require_aware(value)

    @computed_field
    @property
    def summary(self) -> RiskSummary:
        counts = {level: 0 for level in RiskLevel}
        for result in self.results:
            counts[result.risk_level] += 1
        return RiskSummary(
            high=counts[RiskLevel.HIGH],
            medium=counts[RiskLevel.MEDIUM],
            low=counts[RiskLevel.LOW],
            none=counts[RiskLevel.NONE],
        )

    @computed_field
    @property
    def overall_risk_level(self) -> RiskLevel:
        """所有结果中最高的风险等级；没有结果时为 none。"""
        if not self.results:
            return RiskLevel.NONE
        return max((r.risk_level for r in self.results), key=lambda level: level.severity)
