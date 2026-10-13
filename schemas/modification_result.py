"""Modification Agent 通过 Function Calling 调用 modify_clause 工具后，
工具返回的候选修改结果。

这是 Agent/Tool 这一层的"输出契约"，和 ModificationTask（持久化层的任务
记录）是两个不同的东西：一个 ModificationResult 会被包装进
ModificationTask.modification_attempts 里的一条 ModificationAttempt，
但 ModificationResult 本身不知道自己是第几轮尝试、属于哪个任务。
"""

from pydantic import BaseModel, Field


class ModificationResult(BaseModel):
    """modify_clause 工具的返回结果（候选修改，尚未经过校验/确认）。"""

    clause_id: str = Field(..., min_length=1)
    modified_text: str = Field(..., min_length=1)
    reason: str = ""
    legal_basis: list[str] = Field(default_factory=list)
