"""一次已持久化的审查记录。

ReviewReport（review_report.py）是 review pipeline 的直接产出，只描述
"这次审查得到了什么结果"，本身不知道自己是第几次审查、属于哪个合同版本、
什么时候被存下来的。

ReviewRecord 是持久化层的外壳，把这些"存档信息"和 ReviewReport 分开放：
    ReviewRecord
        review_id           这次审查的标识（合同内唯一），例如 "v1_001"
        contract_id
        contract_version    生成这份报告时，合同处于哪个版本（"v1" 或 "v2"；
                             由调用方显式传入，不是本模型自己判断出来的，
                             见 contract/manager.py::save_review 的说明）
        report: ReviewReport
        created_at

不把这些字段直接塞进 ReviewReport，是因为 ReviewReport 已经是一个稳定、经过
测试的契约（pipeline / formatter 都依赖它），持久化相关的字段属于存储层的
关注点，不应该反过来污染 pipeline 的输出契约。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from core._time import require_aware, utc_now
from core.review_report import ReviewReport


class ReviewRecord(BaseModel):
    """一条已保存的审查记录（对应磁盘上的一个 review_<review_id>.json）。"""

    review_id: str = Field(..., min_length=1)
    contract_id: str = Field(..., min_length=1)

    # 版本系统已经存在（ContractVersion + ModificationService.generate_v2）：
    # V1 审查传 "v1"，V2 复审传 "v2"，由调用方显式声明，本字段不自己猜测。
    contract_version: str = Field(default="v1", min_length=1)

    report: ReviewReport

    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return require_aware(value)
