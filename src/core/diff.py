"""V1/V2 之间的条款级 Diff、风险级 Diff 的结果结构。

这两个结构都是"展示用的计算结果"，不落盘持久化（每次请求时基于已经持久化的
Clause / ReviewRecord 现算现返回，本身没有状态），所以没有 created_at 之类的
字段，也不属于"哪份数据存在哪里"这类持久化契约——和 ContractVersion、
ReviewRecord 是不同性质的两类 schema。
"""

from typing import Optional

from pydantic import BaseModel

from core.review_result import RiskLevel


class ClauseDiffEntry(BaseModel):
    """一个条款在 V1 与 V2 之间的对比。"""

    clause_id: str
    matched: bool  # False 表示在另一个版本里找不到同一个 clause_id，不猜测内容
    changed: bool
    original_text: str
    modified_text: Optional[str] = None  # changed=False 或 matched=False 时为 None


class RiskDiffEntry(BaseModel):
    """一条审查结果在 V1 与 V2 之间的风险变化。"""

    category: str  # "resolved" | "unchanged" | "changed" | "new" | "unmatched"
    description: str

    v1_risk_level: Optional[RiskLevel] = None
    v2_risk_level: Optional[RiskLevel] = None

    # 便于前端展示这条结果具体关联哪些条款（不管是 clause_id 还是 related_clause_ids）
    v1_clause_ref: Optional[str] = None
    v2_clause_ref: Optional[str] = None


class RiskDiffResult(BaseModel):
    contract_id: str
    v1_review_id: str
    v2_review_id: str
    entries: list[RiskDiffEntry]
