"""LLM API 连接层：只负责“怎么把 messages 发给 LLM、拿到文本回复”，
不知道 Clause、Evidence、Prompt 模板这些业务概念——那些是 review 包和
llm/prompts.py 的职责。

当前支持 OpenAI 兼容接口（通过官方 openai SDK，指定 base_url 即可接入任何
兼容 OpenAI Chat Completions 格式的服务），并提供一个 DeepSeek 的便捷构造函数。
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from config import settings
from domain.ports import LLMPortError

# DeepSeek 官方 OpenAI 兼容地址（固定写死，不要求写进 .env）。
# 参考：https://api-docs.deepseek.com
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# 默认模型名见 config/settings.py 的 LLM_MODEL_NAME（含 DeepSeek 模型命名变动的说明）。
DEFAULT_DEEPSEEK_MODEL = settings.LLM_MODEL_NAME


class LLMClientError(LLMPortError):
    """LLM 连接/调用失败（缺配置、鉴权失败、网络错误、限流等）。

    只表示“连接层出了问题”，不涉及审查业务逻辑。
    """


class OpenAICompatibleClient:
    """对任意 OpenAI 兼容 Chat Completions 接口的一层薄封装。"""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages: list[dict], temperature: float = 0.0, json_mode: bool = False) -> str:
        """发送一次对话请求，返回模型回复的原始文本（不做任何解析）。

        json_mode=True 时要求模型只输出 JSON（依赖 messages 里已经明确要求
        输出 JSON——多数 OpenAI 兼容服务在开启这个模式时都有此要求）。
        """
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                **kwargs,
            )
        except OpenAIError as exc:
            raise LLMClientError(f"调用 LLM 接口失败：{exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMClientError("LLM 返回了空内容")
        return content

    def chat_with_tool(self, messages: list[dict], tool_schema: dict, temperature: float = 0.0) -> dict:
        """发送一次真正使用 Function Calling 的对话请求，通过给模型只提供
        这一个工具（tools=[tool_schema]），引导它通过调用这个工具来返回
        结构化结果，而不是在文本回复里自由发挥。

        tool_schema 是一个 OpenAI 兼容的单个 tool 定义（
        {"type": "function", "function": {"name": ..., "parameters": {...}}}），
        本方法不做多工具的自主选择——本项目第一版 Modification Agent 明确
        只有一个工具。

        tool_choice 用 "auto" 而不是强制指定这个工具名（P-21，见
        docs/PITFALLS.md）：DeepSeek 的 thinking 模式（部分模型默认开启）
        不支持强制/具名的 tool_choice，会直接返回 400
        "Thinking mode does not support this tool_choice"；"auto" 在
        thinking 模式和非 thinking 模式下都被接受。因为工具集只有一个，
        "auto" 下模型实际只有两种结果："调用这唯一的工具" 或
        "不调用任何工具、直接回文本"——后者已经被下面的
        `if not tool_calls` 分支覆盖，会被上层的 ModificationAgent 包装成
        ModificationAgentError，计入 modification/service.py 的重试轮次，
        不需要新的异常分支。这不会让 Function Calling 变得"不真实"：
        请求依然声明 tools=[tool_schema]，模型依然通过真实的 tool_calls
        字段自己决定要不要调用、怎么填参数，变化的只是"服务端要不要强制"。

        返回该工具调用的参数（已经用 json.loads 解析成 dict），不做任何
        业务校验——参数是否合法、是否满足这个工具的具体约束，由调用方
        （modification/tool.py）负责。

        这是 chat() 之外新增的独立方法，不改变 chat() 原有的行为和调用方；
        只有 Modification Agent 用到它，review 链路继续用 chat()。
        """
        tool_name = tool_schema["function"]["name"]
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                tools=[tool_schema],
                tool_choice="auto",
            )
        except OpenAIError as exc:
            raise LLMClientError(f"调用 LLM 接口失败：{exc}") from exc

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise LLMClientError(f"LLM 没有调用预期的工具 {tool_name!r}（返回了纯文本回复）")

        call = tool_calls[0]
        if call.function.name != tool_name:
            raise LLMClientError(f"LLM 调用了非预期的工具：{call.function.name!r}（预期 {tool_name!r}）")

        try:
            return json.loads(call.function.arguments)
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                f"工具调用参数不是合法 JSON：{exc}\n原始参数：{call.function.arguments!r}"
            ) from exc


def build_deepseek_client(model: Optional[str] = None) -> OpenAICompatibleClient:
    """从 .env / 环境变量读取 DEEPSEEK_API_KEY、DEEPSEEK_MODEL，构造一个客户端。

    .env 只需要配置：
        DEEPSEEK_API_KEY=sk-xxx
        DEEPSEEK_MODEL=deepseek-chat      # 可选，不填则用 DEFAULT_DEEPSEEK_MODEL

    显式传入的 model 参数优先级最高，其次是 .env 里的 DEEPSEEK_MODEL，
    都没有则用 DEFAULT_DEEPSEEK_MODEL。
    """
    load_dotenv()  # 从项目根目录的 .env 加载；已存在于环境变量中的值不会被覆盖
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise LLMClientError("未找到 DEEPSEEK_API_KEY，请在项目根目录的 .env 文件中配置")
    resolved_model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    return OpenAICompatibleClient(api_key=api_key, base_url=DEEPSEEK_BASE_URL, model=resolved_model)
