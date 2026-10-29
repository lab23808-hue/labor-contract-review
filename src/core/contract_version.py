"""合同版本记录：把"V1/V2（以及未来的 V3……）"这个概念落成一个最小、
可扩展的数据模型，而不是只在前端显示一个字符串。

核心语义（Stage 2 明确下来，不是遗漏，是本次要解决的问题）：
    contract_id 唯一标识【一个具体的 Contract 实例】——它自己的原始文件、
    解析文本、Clause 列表、审查记录全部挂在这一个 contract_id 下面。V1 和
    V2 是两个完全独立的 Contract 实例，各自有各自的 contract_id；Review
    从来不知道、也不需要知道自己正在处理的 contract_id 是"V1"还是"V2"。

    真正把"V1/V2 是同一份原始合同的不同版本"这个关系串起来的，只有
    ContractVersion 这一个模型。它必须能表达三件事：
        1) family_id      —— 同一份原始合同的所有版本共享的家族标识。
                              这是"这些 contract_id 其实是同一份合同的不同
                              版本"这件事的唯一依据。
        2) version_number  —— 这个版本在家族里的序号（从 1 开始的整数：
                              V1=1，V2=2……），不是 "v1"/"v2" 这种字符串，
                              避免"version_number 其实是个字符串枚举"这种
                              似是而非的类型。
        3) parent_contract_id —— 这个版本是基于哪一个【具体 contract_id】
                              生成的，不是基于"哪个版本号"。V1→V2 时，
                              parent_contract_id 就是 V1 自己的 contract_id；
                              如果将来支持 V2→V3，parent_contract_id 就是
                              V2 的 contract_id（也就是本记录的
                              linked_contract_id），不会被硬编码成 "v1"。

兼容性说明（为什么没有删掉 contract_id / source_version 这两个旧字段）：
    ContractManager.save_version() 把 ContractVersion 存在【原合同】的目录
    下（contracts/<contract_id>/versions/version_<number>.json），查找时
    按"目录"定位、按 version_number 匹配文件名——这个存储方式本身没有变
    （Storage 边界本次不调整，见 contract/manager.py）。为了不在同一次改动
    里又去改 ContractManager 的存储路径算法，本模型保留了 contract_id 这个
    字段名（语义调整为"family_id 的别名：这个版本所属的合同家族标识"，
    对 V1→V2 这一步，它的取值就是 V1 自己的 contract_id，和过去完全一致，
    现有调用方传参方式不用改）。source_version 同样保留（历史上是一个
    形如 "v1" 的版本号字符串），新增 parent_contract_id 作为它的"升级版"：
    真正可用于支持 V2→V3 的是 parent_contract_id（一个具体 contract_id），
    source_version 只作为人类可读的旧式标签继续存在，不再是任何逻辑判断
    依据。

本阶段实际只会出现一条记录（V1→V2），但字段设计已经支持 V2→V3：下次生成
V3 时，parent_contract_id 传 V2 的 linked_contract_id，family_id（即
contract_id 字段）仍然传 V1 最初的 contract_id，version_number 传 3。
不实现复杂版本树、不支持版本回滚——这两点依然在本次范围之外。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core._time import require_aware, utc_now


class ContractVersion(BaseModel):
    """一条版本记录：描述"某个 contract_id 是同一个合同家族里的第几个版本，
    是基于哪一个 contract_id 生成的"。本阶段实际只会出现
    version_number=2（即 "v2"）的记录。
    """

    version_id: str = Field(..., min_length=1)

    # 合同家族标识：同一份原始合同的所有版本共享这一个值。为保持与存储层
    # （ContractManager 按这个值定位目录）、历史持久化字段名的兼容，字段名
    # 仍然是 contract_id（取值即这个家族里最初的 V1 的 contract_id），但
    # 语义上请把它理解成 family_id——下面的 family_id 是它的只读别名。
    contract_id: str = Field(..., min_length=1)

    version_number: str = Field(..., min_length=1)  # 展示用字符串，目前恒为 "v2"

    # 这个版本【实际生成自】哪一个 contract_id（不是版本号字符串）。
    # V1→V2 时等于 contract_id 字段的值；V2→V3 时会等于 V2 自己的
    # linked_contract_id——用一个真实存在的 contract_id 表达"从谁生成"，
    # 不再把它编码成 "v1" 这种版本号字符串。缺省时回填为 contract_id，
    # 对应"本阶段这条记录永远是从 V1 生成"的既有行为，调用方不传这个参数
    # 也能得到和 Stage 1 完全一致的结果。
    parent_contract_id: Optional[str] = Field(default=None, min_length=1)

    # 历史字段：生成时间点上"基于哪个版本"的人类可读标签（例如 "v1"）。
    # 保留只是为了不破坏已经依赖这个字段名的旧调用方/旧数据；新逻辑应该读
    # parent_contract_id，不要再读这个字符串做任何判断。
    source_version: str = Field(default="v1", min_length=1)

    # 这个版本的条款原文/审查记录实际存放在哪个（内部）contract_id 下面。
    linked_contract_id: str = Field(..., min_length=1)

    created_at: datetime = Field(default_factory=utc_now)
    created_by: str = Field(default="lawyer", min_length=1)  # 当前没有用户体系，先用简单值

    status: str = Field(default="active", min_length=1)

    @model_validator(mode="after")
    def _default_parent_to_family_root(self) -> "ContractVersion":
        """parent_contract_id 缺省时回填为 contract_id（family_id）。

        这是本阶段（只有 V1→V2 这一种转移）的默认行为：没有显式指定
        parent_contract_id 时，等价于"这个版本是从家族最初的 V1 生成的"，
        和 Stage 1 时期隐含的假设完全一致。未来生成 V2→V3 时，调用方必须
        显式传入 parent_contract_id=V2 的 contract_id，不能依赖这个默认值。
        """
        if self.parent_contract_id is None:
            self.parent_contract_id = self.contract_id
        return self

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return require_aware(value)

    @property
    def family_id(self) -> str:
        """contract_id 字段的只读别名，语义更贴近"合同家族标识"。"""
        return self.contract_id
