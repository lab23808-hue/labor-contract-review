"""llm：对 LLM API 的连接层。

只负责"怎么把 messages 发给 LLM、拿到回复"，不包含审查业务逻辑（那是
agents 包的职责）、不做检索（那是 rag 包的职责）、不持有任何 Prompt 模板
（那是 prompts 包的职责，位于 llm 之上，llm 不反过来依赖它）。
"""

from infra.llm.client import (
    DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    LLMClientError,
    OpenAICompatibleClient,
    build_deepseek_client,
)

__all__ = [
    "OpenAICompatibleClient",
    "LLMClientError",
    "build_deepseek_client",
    "DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
]
