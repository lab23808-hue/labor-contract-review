"""修改任务的数据结构：律师针对某个条款提出的修改诉求，以及它在
Modification Agent 工作流中的完整生命周期。

ModificationTask 和 ReviewResult 是两个不同层次的业务概念，故意不合并：
    ReviewResult      —— Agent（LLM / 规则）对条款做出的风险判断，机器生成。
    ModificationTask  —— 人（律师）看完判断之后提出的"我要怎么改"，人类生成，
                          后续由 Modification Agent 消费、由律师确认。

本次改动（见 docs/PITFALLS.md / docs/DEVELOPMENT_LOG.md 对应日期的记录）：
    1. 引入 ModificationBatch（schemas/modification_batch.py）：律师显式开启
       一轮修改后得到一个 batch_id，此后创建的每一条 ModificationTask 都必须
       显式携带 batch_id——不再有"默认 batch"、不再靠猜测归属。
    2. 新增 source_review_id + source_review_snapshot：任务创建时冻结一份
       【当时】的 ReviewResult 快照，即便后续合同被重新审查，这份快照也
       永远不变——Modification Agent 的 Prompt、Risk Analyzer 的风险对比，
       都应该基于这份不会漂移的快照，而不是"当前最新一次审查"。
    3. 去掉 COMPLETED 终态：V2 是否生成成功，记录在 ModificationBatch 上，
       不再记录在 Task 上——CONFIRMED 的任务在 V2 生成之后依然是 CONFIRMED，
       永久保留"律师确认过这个结果"这个事实。
    4. 新增 ABANDONED 终态：REJECTED/NEEDS_HUMAN 状态下，律师可以明确放弃
       这条修改任务（不再重试），对应 ModificationService.abandon。

状态机（6 个状态）：

    pending  ──start──▶ waiting_confirmation ──confirm──▶ confirmed
       ▲                    │
       │                  reject（附带新的律师意见）
       │                    ▼
       └──────────────── rejected ──（重试次数已达上限）──▶ needs_human
                    （attempts < 3 时可以再次 start）

    rejected / needs_human ──abandon──▶ abandoned

    - pending                任务已创建，还没有产生过候选修改（或候选被拒绝
                              后回到可重试状态）
    - waiting_confirmation    Modification Agent 产生了一个通过 Validator 的
                              候选，并已经完成（或尝试完成）修改后风险分析，
                              等待律师确认
    - rejected                律师明确拒绝了当前候选；本身不是终态——只要
                              attempts < 3，仍然可以基于新的律师意见重新调用
                              start，也可以调用 abandon 放弃
    - needs_human             已经尝试满 3 轮仍未得到律师确认，系统不再自动
                              重试；可以调用 confirm（附带律师手工确定的结果）
                              或 abandon
    - confirmed                律师确认了某一轮候选结果（或 needs_human 下
                              律师手工确定的结果），终态：V2 生成成功与否都
                              不会改变这个状态
    - abandoned                 律师明确放弃这条修改任务，终态

    CONFIRMED / ABANDONED 都是终态，不存在 "→ COMPLETED" 这种转换——V2 是否
    生成成功记录在 ModificationBatch 上（见 schemas/modification_batch.py）。

要求：
    1. 一个任务对应一个目标条款（target_clause_id），属于一个确定的 batch_id
    2. 原始条款必须保存（original_text，创建后不可变，且必须由服务端从
       ContractManager 查出，不信任客户端传入的值）
    3. 每次修改结果必须可追踪（modification_attempts，只增不减、不覆盖）
    4. 原始条款不能被覆盖（original_text 字段本身永不修改；候选结果只写入
       current_modified_text / modification_attempts）
    5. 修改历史不能丢失（同上）
    6. source_review_snapshot 创建后永不修改（即使合同被重新审查）
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core._time import require_aware, utc_now
from core.review_result import ReviewResult, RiskLevel


class ModificationTaskStatus(str, Enum):
    PENDING = "pending"
    WAITING_CONFIRMATION = "waiting_confirmation"
    REJECTED = "rejected"
    NEEDS_HUMAN = "needs_human"
    CONFIRMED = "confirmed"
    ABANDONED = "abandoned"


class RiskResolution(str, Enum):
    """修改后风险分析的结论：原始风险在这一轮候选里是否被化解。

    由业务比较逻辑（modification/risk_resolution.py 的纯函数）产出，不是
    Risk Analyzer（ClauseReviewer）自己判断的——Risk Analyzer 只负责对
    "修改后的文本"重新跑一次独立审查，得到一个新的 ReviewResult；
    "这个新结果相比原始风险算不算解决"是本系统自己的业务规则。
    """

    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"


MAX_MODIFICATION_ATTEMPTS = 3


class ReviewResultSnapshot(BaseModel):
    """ReviewResult 的一份冻结快照：只保留业务上关心、且创建后不应再变化的
    几个字段，不是 ReviewResult 的别名或子类——即便未来 ReviewResult 增加
    字段，这份快照的形状也不会被动跟着变化，这是"冻结"这个词的字面含义。
    """

    risk: bool
    risk_level: RiskLevel
    reason: str
    legal_basis: list[str] = Field(default_factory=list)
    suggestion: str = ""

    @classmethod
    def from_review_result(cls, result: ReviewResult) -> "ReviewResultSnapshot":
        return cls(
            risk=result.risk,
            risk_level=result.risk_level,
            reason=result.reason,
            legal_basis=list(result.legal_basis),
            suggestion=result.suggestion,
        )


class ModificationAttempt(BaseModel):
    """一轮"Agent 生成候选 + Validator 校验 + 修改后风险分析"的完整记录。

    不管 Validator 是否通过都会记录一条，这样律师/开发者能看到"为什么这一轮
    没有进入确认阶段"，而不是只留下最后一次成功的结果。risk_analysis 相关
    三个字段只在 validator_passed=True 时才有意义被填充；Validator 没通过
    的轮次根本不会跑风险分析（候选本身都不合格，分析它的风险没有意义）。
    """

    attempt_number: int = Field(..., ge=1, le=MAX_MODIFICATION_ATTEMPTS)

    # 生成这一轮候选时使用的律师意见（累计到这一轮为止的最新一条指示，
    # 不是全部历史拼接——历史本身通过 lawyer_instructions 列表保留）。
    lawyer_instruction: str = Field(..., min_length=1)

    candidate_text: Optional[str] = None
    reason: str = ""
    legal_basis: list[str] = Field(default_factory=list)

    validator_passed: bool
    validator_errors: list[str] = Field(default_factory=list)

    # 修改后风险分析（Part D/E）：对候选文本重新跑一次独立审查得到的结果。
    # 调用 Risk Analyzer 失败时为 None，原因记在 risk_analysis_error。
    risk_analysis: Optional[ReviewResult] = None
    risk_analysis_error: Optional[str] = None
    # 原始风险（source_review_snapshot.risk_level）与 risk_analysis.risk_level
    # 的业务比较结论；Risk Analyzer 失败时固定为 UNKNOWN。
    risk_resolution: Optional[RiskResolution] = None

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return require_aware(value)


class ModificationTask(BaseModel):
    """一条修改任务（律师对某个条款提出的修改意见）。"""

    task_id: str = Field(..., min_length=1)
    contract_id: str = Field(..., min_length=1)

    # 这条任务所属的批次；本阶段起每条任务必须显式携带 batch_id，不再有
    # "默认 batch"（见 schemas/modification_batch.py）。
    batch_id: str = Field(..., min_length=1)

    # 这条任务是针对哪一次审查提出的（ReviewRecord.review_id）。
    source_review_id: str = Field(..., min_length=1)

    # 创建任务时冻结的原始 ReviewResult 快照；创建后永不修改，即便合同被
    # 重新审查也不会漂移（见模块文档）。
    source_review_snapshot: ReviewResultSnapshot

    # 任务针对哪个条款；本阶段要求律师必须选中一个具体条款才能提交任务
    # （即便触发入口是一条 clause_id 为空、related_clause_ids 关联多个条款的
    # ReviewResult，前端也需要让律师明确选出其中一个条款来提交）。
    target_clause_id: str = Field(..., min_length=1)

    # 被修改条款当时的原文，冗余保存一份且创建后不可变。必须由服务端从
    # ContractManager 查出（contract_id + target_clause_id -> Clause.original_text），
    # 绝不信任客户端传入的值——见 modification/service.py::create_task。
    original_text: str = Field(..., min_length=1)

    # 律师历次输入的修改意见，按时间顺序累加，永不删除/覆盖。创建任务时的
    # 第一条意见是 lawyer_instructions[0]；每次拒绝重改都会追加一条。
    lawyer_instructions: list[str] = Field(..., min_length=1)

    status: ModificationTaskStatus = ModificationTaskStatus.PENDING

    # 完整的修改历史：每一轮 Agent 生成 + Validator 校验 + 风险分析的记录，
    # 只追加不覆盖。
    modification_attempts: list[ModificationAttempt] = Field(default_factory=list)

    # 当前等待律师确认（status=waiting_confirmation）或已被确认
    # （status=confirmed）的候选文本；只在这两种状态下有意义，其余状态下为 None。
    current_modified_text: Optional[str] = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    confirmed_at: Optional[datetime] = None

    @field_validator("created_at", "updated_at", "confirmed_at")
    @classmethod
    def _require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return value
        return require_aware(value)

    @property
    def lawyer_instruction(self) -> str:
        """最初创建任务时律师给出的修改意见（兼容旧字段名的只读视图）。"""
        return self.lawyer_instructions[0]

    @property
    def attempts_exhausted(self) -> bool:
        """是否已经用满最大重试轮次（前端据此决定是否还能发起下一轮修改）。"""
        return len(self.modification_attempts) >= MAX_MODIFICATION_ATTEMPTS

    @property
    def can_start(self) -> bool:
        """当前是否允许发起（下）一轮 Modification Agent 调用。"""
        return self.status in (ModificationTaskStatus.PENDING, ModificationTaskStatus.REJECTED)

    @property
    def is_terminal(self) -> bool:
        """是否已经进入终态（CONFIRMED / ABANDONED），不会再发生状态转换。"""
        return self.status in (ModificationTaskStatus.CONFIRMED, ModificationTaskStatus.ABANDONED)
