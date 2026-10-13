"""合同条款的数据结构。

用途：条款定位、前端展示、审计追踪、后续版本修改。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class Clause(BaseModel):
    """一个合同条款（ClauseSplitter 的输出单元）。"""

    # 所属合同。clause_id 只在一份合同内唯一，
    # 全局唯一标识是 (contract_id, clause_id)；数据库查询、多合同并存都依赖它。
    contract_id: str = Field(..., min_length=1)

    # 条款唯一标识（合同内），例如 "clause_003" 或 "clause_003_1"
    clause_id: str = Field(..., min_length=1)

    # 条款类型，例如 "工作地点"、"试用期"、"薪资"。
    # 切分阶段可能还识别不出来，所以给默认值，后续可由分类步骤补充。
    clause_type: str = "unknown"

    # 条款原文
    original_text: str = Field(..., min_length=1)

    # 所在页码。txt 没有页码，因此可选；PDF/DOCX 阶段再填充。
    page_number: Optional[int] = Field(default=None, ge=1)

    # 条款在“整份合同全文”中的字符偏移，左闭右开：full_text[start_char:end_char]
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., ge=0)

    # 父条款的 clause_id。顶层条款（如“第三条”）为 None，
    # 其下的款项（如“1.乙方工作地点为北京市。”）指向父条款。
    parent_clause: Optional[str] = None

    # 层级：0 = 条（第X条），1 = 款（1.），2 = 项（(1)）……
    hierarchy_level: int = Field(default=0, ge=0)

    # 扩展信息，避免今后每加一个字段都要改契约
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_char_range(self) -> "Clause":
        if self.end_char < self.start_char:
            raise ValueError("end_char 不能小于 start_char")
        return self
