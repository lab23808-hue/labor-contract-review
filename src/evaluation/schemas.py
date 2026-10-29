"""标准答案（golden sample）的数据结构。

这些 schema 独立于 `core/`（生产数据模型）——标准答案描述的是"人工/开发者
认为应该是什么"，不是"系统实际产出的是什么"，两者故意不共享类型，即使字段
名看起来相似（这和 `core/modification_task.py::ReviewResultSnapshot` 相对
`ReviewResult`"故意不是别名或子类"的理由一样：标准答案的形状不应该被动跟着
生产 schema 的变化而变化）。

本文件只放数据结构，不做评估计算（比对逻辑在 `evaluation/diagnostics.py`）。
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class VerificationStatus(str, Enum):
    """这条标准答案的核验状态。

    本次任务没有独立法律复核人员参与标注（任务要求第 3.3.6 条明确要求：没有
    独立复核人员时必须说明基准仍属于"待人工确认的候选基准"）——所以本次生成
    的全部标准答案，核验状态只会是 CANDIDATE 或 PENDING_REVIEW 两种，不存在
    VERIFIED（那需要真正的人工法律复核，本次任务不具备这个条件，不伪装成有）。
    """

    CANDIDATE = "candidate"  # 开发者/模型根据知识库条文设计的候选答案，未经独立法律复核
    PENDING_REVIEW = "pending_review"  # 存在争议、依赖未核验的法律依据、或条件不够明确，暂不计入严格准确率


class ClauseAnswer(BaseModel):
    """一个条款的标准答案。"""

    clause_id: str = Field(..., min_length=1)
    order: int = Field(..., ge=0)  # 在合同里的顺序，从 0 开始
    start_char: int = Field(..., ge=0)  # 标准条款切分边界：在合同全文里的起始位置
    end_char: int = Field(..., gt=0)  # 标准条款切分边界：结束位置（不含）
    original_text: str = Field(..., min_length=1)
    clause_type: str = Field(..., min_length=1)  # 条款类型标签，如"试用期工资"

    risk: bool
    risk_type: Optional[str] = None  # 风险类型标签，如"试用期工资低于法定标准"；risk=False 时应为 None
    risk_level: Optional[str] = None  # "none"/"low"/"medium"/"high"；risk=False 时应为 "none" 或 None

    reasoning: str = Field(..., min_length=1)  # 判断理由

    legal_basis: list[str] = Field(default_factory=list)  # 如 ["《劳动合同法》第二十条"]
    legal_basis_verified_in_sources: bool = Field(
        ...,
        description=(
            "这条法律依据是否能在 data/knowledge/SOURCES.md 里找到对应的、"
            "结构核验通过的条文记录——不是说条文文本逐字核验过（本知识库目前没有一条做到这一点，"
            "见 SOURCES.md），只是说这个条号确实存在于知识库并且本次标注时核对过。"
        ),
    )
    basis_link_explanation: str = Field(
        default="", description="法律依据与风险结论之间的关联说明：为什么这条法条支持这个结论"
    )

    suggestion: str = Field(default="", description="可执行的修改建议；无风险时可为空字符串")

    context_dependent_condition: Optional[str] = Field(
        default=None, description="必须结合上下文（其他条款/未写明信息）才能判断的条件，没有则为 None"
    )
    acceptable_alternative_judgments: list[str] = Field(
        default_factory=list, description="允许接受的其他合理判断（例如风险等级在 medium/high 之间都算合理）"
    )
    pending_review_note: Optional[str] = Field(
        default=None, description="无法确定或需要人工法律复核的具体原因；没有则为 None"
    )

    annotated_by: str = Field(..., min_length=1)
    verification_status: VerificationStatus
    annotation_basis: str = Field(
        ..., min_length=1, description="标注依据：参照了哪份知识库条文/规则/先前案例"
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> "ClauseAnswer":
        if self.end_char <= self.start_char:
            raise ValueError("end_char 必须大于 start_char")
        if not self.risk and self.risk_type is not None:
            raise ValueError("risk=False 时 risk_type 必须为 None（没有风险就不该有风险类型标签）")
        if self.risk and not self.legal_basis and self.pending_review_note is None:
            raise ValueError(
                "risk=True 但没有 legal_basis 且没有 pending_review_note 说明原因——"
                "标准答案要求“法律依据与风险结论之间的关联”，risk 结论不能没有依据也不说明理由"
            )
        if self.legal_basis and not self.legal_basis_verified_in_sources and self.verification_status == VerificationStatus.CANDIDATE:
            raise ValueError(
                "引用了 legal_basis 但 legal_basis_verified_in_sources=False，且状态是 candidate——"
                "这种情况应该标成 pending_review，不能当作候选答案直接使用"
            )
        return self


class ContractSampleType(str, Enum):
    CLEAR_RISK = "clear_risk"  # 明确存在风险的合同
    BASICALLY_COMPLIANT = "basically_compliant"  # 基本合规的合同
    MIXED = "mixed"  # 同时包含风险和合规条款
    BOUNDARY_COMPLEX = "boundary_complex"  # 边界、复杂及组合场景


class ContractAnswer(BaseModel):
    """一份合同的标准答案（包含它全部条款的标准答案）。"""

    sample_id: str = Field(..., min_length=1)
    contract_version: str = Field(default="v1")
    sample_type: ContractSampleType
    source: str = Field(..., min_length=1)  # "existing_sample" 或 "newly_designed"，记录来自哪里
    description: str = Field(..., min_length=1)  # 这份合同设计意图的简述

    full_text: str = Field(..., min_length=1)
    clauses: list[ClauseAnswer] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_clauses_cover_full_text_without_gap_or_overlap(self) -> "ContractAnswer":
        ordered = sorted(self.clauses, key=lambda c: c.order)
        if [c.order for c in ordered] != list(range(len(ordered))):
            raise ValueError("clauses 的 order 必须是从 0 开始的连续序列，不能有空缺或重复")

        for i in range(len(ordered) - 1):
            if ordered[i].end_char > ordered[i + 1].start_char:
                raise ValueError(
                    f"条款 {ordered[i].clause_id} 和 {ordered[i + 1].clause_id} 的标准切分边界重叠"
                )

        for clause in ordered:
            if self.full_text[clause.start_char : clause.end_char] != clause.original_text:
                raise ValueError(
                    f"条款 {clause.clause_id} 的 start_char/end_char 切出来的文本和 original_text 不一致——"
                    "标准答案自己的切分边界必须和自己的原文对得上"
                )

        clause_ids = [c.clause_id for c in self.clauses]
        if len(set(clause_ids)) != len(clause_ids):
            raise ValueError("clause_id 在同一份合同标准答案里必须唯一")

        return self

    @property
    def risk_clause_count(self) -> int:
        return sum(1 for c in self.clauses if c.risk)

    @property
    def compliant_clause_count(self) -> int:
        return sum(1 for c in self.clauses if not c.risk)
