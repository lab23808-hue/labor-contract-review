"""ModificationBatch：一轮修改的容器。

为什么需要这个概念（Part F）：ModificationTask 之前隐式地属于"某份合同的
所有未完成任务"，V2 生成的就绪判断（generate_v2 旧实现）直接扫描这份合同
下的全部任务。这在"律师想对同一份合同分两轮分别处理一批条款、先生成一个
V2，再在这个 V2 基础上继续改"的场景下会出问题——没有办法区分"这一批任务
是为了这一次 V2"还是"上一次已经生成过 V2 的那批"。

ModificationBatch 把"一轮修改"显式建模成一个实体：
    - 律师显式创建一个 batch（对应某次 source_review_id），得到 batch_id；
    - 此后创建的每一条 ModificationTask 都必须显式携带这个 batch_id；
    - V2 的生成以 batch 为单位：一个 batch 只会生成一个 V2（成功生成后
      generated_contract_id 被设置，不允许再对同一个 batch 生成第二次）；
    - 批次的就绪判断（能不能生成 V2）只看"这个 batch 里的任务"，不看这份
      合同下所有历史任务。

持久化方式：和 ModificationTask 一样，存在【原合同】目录下的独立 JSON 文件
（contract/manager.py 新增 _MODIFICATION_BATCHES_DIR，文件命名/读写模式与
modification_tasks 完全一致），不使用数据库。
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from schemas._time import require_aware, utc_now


class ModificationBatchStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    READY_FOR_V2 = "ready_for_v2"
    V2_GENERATING = "v2_generating"
    V2_GENERATED = "v2_generated"
    V2_FAILED = "v2_failed"


class ModificationBatch(BaseModel):
    """一轮修改：从律师显式"开始一轮修改"到（最多）生成一个 V2 的完整容器。"""

    batch_id: str = Field(..., min_length=1)

    # 这个批次所属的（V1）合同 contract_id。
    source_contract_id: str = Field(..., min_length=1)

    # 这个批次针对哪一次审查发起（ReviewRecord.review_id）。
    source_review_id: str = Field(..., min_length=1)

    # 属于这个批次的全部 ModificationTask.task_id，只追加不覆盖。
    task_ids: list[str] = Field(default_factory=list)

    status: ModificationBatchStatus = ModificationBatchStatus.IN_PROGRESS

    # V2 生成成功后，指向 V2 真正的数据宿主 contract_id（ContractManager
    # 内部登记的新 contract_id，不是 ContractVersion.version_id）。
    generated_contract_id: Optional[str] = None

    # V2_FAILED 时的失败原因，便于排查；成功或尚未尝试时为 None。
    last_error: Optional[str] = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return require_aware(value)
