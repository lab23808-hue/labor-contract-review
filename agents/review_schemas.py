"""review 模块自己的数据结构：LLM 必须返回的原始 JSON 结构。

注意区分：这不是系统最终对外的审查结果——最终结果是全局共用的
schemas.ReviewResult（被 ReviewReport 依赖，规则检查和 LLM 审查产出同一种）。

LLMReviewOutput 只描述“LLM 这次调用应该回答成什么形状”：clause_id、source
这些字段不该让模型自己填，是 reviewer.py 在校验通过后拼上去的。
"""

from pydantic import BaseModel, Field, model_validator

from schemas import RiskLevel


class LLMReviewOutput(BaseModel):
    """LLM 审查一个条款后应该返回的 JSON 结构。"""

    risk: bool
    risk_level: RiskLevel
    reason: str = Field(..., min_length=1)
    legal_basis: list[str] = Field(default_factory=list)
    suggestion: str = ""

    @model_validator(mode="after")
    def _check_risk_matches_level(self) -> "LLMReviewOutput":
        if self.risk != (self.risk_level != RiskLevel.NONE):
            raise ValueError("risk 与 risk_level 不一致：risk_level 为 none 时 risk 必须为 False，否则为 True")
        return self
