"""合同管理记录的数据结构（对应 SQLite 中保存的合同元数据）。

只描述“这份合同是什么、处理到哪一步了”，不包含文件路径：
文件按约定放在 contracts/<contract_id>/ 下（original_file、parsed_text、clauses、report），
路径由 contract 模块根据配置的根目录和 contract_id 推导，这样整个目录搬家时数据库不用改。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core._time import require_aware, utc_now


class ContractStatus(str, Enum):
    """合同处理状态。"""

    UPLOADED = "uploaded"  # 已上传，原文件已保存
    PARSED = "parsed"  # 已解析出原文
    SPLIT = "split"  # 已切分成条款
    REVIEWED = "reviewed"  # 已生成审查报告
    FAILED = "failed"  # 某一步失败，原因见 error


class Contract(BaseModel):
    """一份合同的元数据。"""

    contract_id: str = Field(..., min_length=1)

    # 上传时的原始文件名
    filename: str = Field(..., min_length=1)

    # 文件格式：小写扩展名，不带点，例如 "txt"、"pdf"
    file_format: str = Field(..., pattern=r"^[a-z0-9]+$")

    # 原文件内容的 SHA-256（小写十六进制），用于识别重复上传
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    size_bytes: int = Field(..., ge=0)

    status: ContractStatus = ContractStatus.UPLOADED

    # 失败原因；只有 status 为 failed 时必须填写
    error: Optional[str] = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    # 扩展信息，例如识别出的文本编码
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return require_aware(value)

    @model_validator(mode="after")
    def _failed_needs_error(self) -> "Contract":
        if self.status == ContractStatus.FAILED and not self.error:
            raise ValueError("status 为 failed 时必须填写 error")
        return self
