"""单条审查结果的数据结构。

规则检查和 LLM 审查产出同一种 ReviewResult，用 source 区分来源，
这样 pipeline 合并、formatter 输出时不需要处理两种格式。
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class RiskLevel(str, Enum):
    """风险等级。

    程序内部统一使用英文值，界面展示时通过 RISK_LEVEL_LABELS_ZH 或
    ReviewResult.risk_level_zh 转成中文。none 表示“已检查，未发现问题”。
    继承 str 是为了让它能直接序列化成 JSON 字符串、也能与字符串比较。
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def severity(self) -> int:
        """严重程度数值，用于比较和取最大值（none < low < medium < high）。"""
        return _SEVERITY[self]


_SEVERITY = {RiskLevel.NONE: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}

# 界面展示用的中文标签
RISK_LEVEL_LABELS_ZH: dict[RiskLevel, str] = {
    RiskLevel.NONE: "无",
    RiskLevel.LOW: "低",
    RiskLevel.MEDIUM: "中",
    RiskLevel.HIGH: "高",
}


class ReviewSource(str, Enum):
    """审查结果的来源。"""

    LLM = "llm"  # 条款级：RAG + LLM
    RULE = "rule"  # 合同级：规则检查


class ReviewResult(BaseModel):
    """一条审查结果。

    - LLM 来源：针对某个条款，必须有 clause_id。
    - 规则来源：必须有 rule_id；clause_id 可为空——
      “合同缺少必备条款”这类问题没有对应的条款；
      跨条款问题（如试用期与合同期限）用 related_clause_ids 列出涉及的条款。
    """

    # 对应 Clause.clause_id（合同内唯一）。缺失类问题为 None。
    clause_id: Optional[str] = Field(default=None, min_length=1)

    # 跨条款问题涉及的其他条款
    related_clause_ids: list[str] = Field(default_factory=list)

    # 是否存在风险；必须与 risk_level 一致：risk_level 为 none 才是 False
    risk: bool

    risk_level: RiskLevel

    # 判断理由（有风险时是风险原因；无风险时说明为何合规）
    reason: str

    # 法律依据，例如 ["《劳动合同法》第十七条"]。无依据时为空列表。
    legal_basis: list[str] = Field(default_factory=list)

    # 修改建议；无风险时可为空字符串
    suggestion: str = ""

    source: ReviewSource

    # 规则来源时的规则编号，便于追溯是哪条规则触发的
    rule_id: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_consistency(self) -> "ReviewResult":
        if self.risk != (self.risk_level != RiskLevel.NONE):
            raise ValueError("risk 与 risk_level 不一致：risk_level 为 none 时 risk 必须为 False，否则为 True")
        if self.source == ReviewSource.LLM:
            if self.clause_id is None:
                raise ValueError("LLM 来源的审查结果必须有 clause_id")
            if self.rule_id is not None:
                raise ValueError("LLM 来源的审查结果不应有 rule_id")
        elif self.rule_id is None:
            raise ValueError("规则来源的审查结果必须有 rule_id")
        return self

    @property
    def risk_level_zh(self) -> str:
        """界面展示用的中文风险等级。"""
        return RISK_LEVEL_LABELS_ZH[self.risk_level]
