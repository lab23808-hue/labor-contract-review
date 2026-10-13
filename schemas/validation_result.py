"""ModificationValidator 的输出：一次程序化校验的结论。

只表达"通过还是不通过、为什么不通过"，不包含任何"这样改是否真的合法/
是否消除了风险"的判断——那是 V2 重新审查的职责，不是 Validator 的职责。
"""

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
