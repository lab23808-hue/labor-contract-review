"""RAG 检索结果（法律依据）的数据结构。"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """一条检索到的法律依据。

    注意：Evidence 只负责“提供依据”，不包含任何法律判断。
    相似度分数等检索信息可放在 metadata 中（如 metadata["score"]）。
    """

    # 法条/法律文本内容
    content: str = Field(..., min_length=1)

    # 来源，例如 "中华人民共和国劳动合同法"
    source: str = Field(..., min_length=1)

    # 条文编号，例如 "第十七条"；有些资料切出来没有明确条号，所以可选
    article: Optional[str] = None

    metadata: dict[str, Any] = Field(default_factory=dict)
