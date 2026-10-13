"""替代测试（明确标注为 mock）：ModificationAgent + llm.client.chat_with_tool
的 Function Calling 解析逻辑，用一个假的 openai 客户端模拟 tool_calls 返回。

这不是真实 LLM 集成测试（openai 包本身在沙箱里不可用，也没有配置
DEEPSEEK_API_KEY），而是验证"拿到 OpenAI SDK 风格的 tool_calls 响应之后，
llm/client.py::chat_with_tool 和 modification/agent.py::ModificationAgent
能不能正确解析/校验"这条纯 Python 逻辑链路，用真实的 json.loads、真实的
pydantic 校验、真实的 execute_modify_clause 越界检查。
"""

import json
import sys
import types

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# ---- 构造一个足以让 llm/client.py 的类型引用通过、且行为可控的假 openai ----
fake_openai = types.ModuleType("openai")


class _FakeOpenAIError(Exception):
    pass


fake_openai.OpenAIError = _FakeOpenAIError
fake_openai.OpenAI = object  # 不会被用来真的实例化
sys.modules["openai"] = fake_openai


def _stub_module(name: str, **attrs) -> None:
    try:
        __import__(name)
        return
    except ModuleNotFoundError:
        pass
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass


_stub_module("langchain_text_splitters", RecursiveCharacterTextSplitter=_Dummy)
_stub_module("langchain_chroma", Chroma=_Dummy)
_stub_module("langchain_core")
_stub_module("langchain_core.documents", Document=_Dummy)
_stub_module("langchain_core.embeddings", Embeddings=_Dummy)
_stub_module("langchain_huggingface", HuggingFaceEmbeddings=_Dummy)
_stub_module("langgraph")
_stub_module("langgraph.graph", END="__end__", START="__start__", StateGraph=_Dummy)

from agents.modification_agent import ModificationAgent, ModificationAgentError
from contract import ContractManager  # noqa: F401  (仅确认无循环导入问题)
from llm.client import LLMClientError, OpenAICompatibleClient
from prompts.modification import MODIFY_CLAUSE_TOOL_SCHEMA
from schemas import Clause

assertions = 0


def check(cond, msg):
    global assertions
    assertions += 1
    if not cond:
        raise AssertionError(f"FAILED #{assertions}: {msg}")
    print(f"  ok  [{assertions}] {msg}")


class _FakeToolCallFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name, arguments):
        self.function = _FakeToolCallFunction(name, arguments)


class _FakeMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, tool_calls):
        self.choices = [_FakeChoice(_FakeMessage(tool_calls))]


class _FakeChatCompletions:
    def __init__(self, response_or_error):
        self._response_or_error = response_or_error
        self.last_kwargs = None  # 记录最近一次真正发出去的请求参数，供断言核对

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._response_or_error, Exception):
            raise self._response_or_error
        return self._response_or_error


class _FakeChat:
    def __init__(self, response_or_error):
        self.completions = _FakeChatCompletions(response_or_error)


class _FakeRawClient:
    def __init__(self, response_or_error):
        self.chat = _FakeChat(response_or_error)


class _FakeCompatibleClient(OpenAICompatibleClient):
    """跳过父类真实构造（不连网络），直接注入一个假的底层 _client。"""

    def __init__(self, response_or_error):
        self.model = "fake-model"
        self._client = _FakeRawClient(response_or_error)


clause = Clause(
    contract_id="c1",
    clause_id="clause_003",
    original_text="第三条 试用期\n试用期为一个月。",
    start_char=0,
    end_char=20,
    hierarchy_level=0,
    metadata={"article_no": "第三条"},
)

# 1. 正常路径：模型正确调用了 modify_clause，参数合法
good_call = _FakeToolCall(
    "modify_clause",
    json.dumps({"clause_id": "clause_003", "modified_text": "第三条 试用期\n试用期为两个月。", "reason": "延长试用期", "legal_basis": []}, ensure_ascii=False),
)
client = _FakeCompatibleClient(_FakeResponse([good_call]))
agent = ModificationAgent(client)
result = agent.generate_candidate(clause, None, ["延长试用期"])
check(result.clause_id == "clause_003", "正常路径应正确解析出 clause_id")
check("两个月" in result.modified_text, "正常路径应正确解析出 modified_text")

# P-21 回归检查（docs/PITFALLS.md）：真正发给 DeepSeek 的 tool_choice 必须是
# "auto"，不能是强制指定函数名的形式——后者在 thinking 模式下会被 DeepSeek
# 拒绝（400 "Thinking mode does not support this tool_choice"）。这里直接
# 检查 chat_with_tool 真实传给底层 SDK 的 kwargs，不是猜测代码行为。
sent_kwargs = client._client.chat.completions.last_kwargs
check(sent_kwargs is not None, "应该真的调用了 chat.completions.create")
check(sent_kwargs.get("tool_choice") == "auto", f"tool_choice 必须是 'auto'（P-21 修复点），实际：{sent_kwargs.get('tool_choice')!r}")
check(sent_kwargs.get("tools") == [MODIFY_CLAUSE_TOOL_SCHEMA], "tools 里仍然声明了完整的 modify_clause 工具定义（真正的 Function Calling，不是退化成普通 JSON 输出）")

# 2. 模型没有调用工具，直接回了文本
no_call_client = _FakeCompatibleClient(_FakeResponse([]))
agent2 = ModificationAgent(no_call_client)
try:
    agent2.generate_candidate(clause, None, ["延长试用期"])
    check(False, "模型不调用工具时应该抛出异常")
except ModificationAgentError as exc:
    check("没有调用预期的工具" in str(exc), f"异常信息应说明模型没有调用工具，实际：{exc}")

# 3. 模型调用了错误的工具名
wrong_tool_call = _FakeToolCall("some_other_tool", "{}")
wrong_tool_client = _FakeCompatibleClient(_FakeResponse([wrong_tool_call]))
agent3 = ModificationAgent(wrong_tool_client)
try:
    agent3.generate_candidate(clause, None, ["延长试用期"])
    check(False, "模型调用了错误的工具名时应该抛出异常")
except ModificationAgentError as exc:
    check("非预期的工具" in str(exc), f"异常信息应说明工具名不对，实际：{exc}")

# 4. 工具参数不是合法 JSON
bad_json_call = _FakeToolCall("modify_clause", "{not valid json")
bad_json_client = _FakeCompatibleClient(_FakeResponse([bad_json_call]))
agent4 = ModificationAgent(bad_json_client)
try:
    agent4.generate_candidate(clause, None, ["延长试用期"])
    check(False, "参数不是合法 JSON 时应该抛出异常")
except ModificationAgentError as exc:
    check("不是合法 JSON" in str(exc), f"异常信息应说明 JSON 不合法，实际：{exc}")

# 5. 模型越界：clause_id 对不上目标条款（tool.py 的第一道防线）
wrong_clause_call = _FakeToolCall(
    "modify_clause",
    json.dumps({"clause_id": "clause_999", "modified_text": "改了别的条款", "reason": "跑题了"}, ensure_ascii=False),
)
wrong_clause_client = _FakeCompatibleClient(_FakeResponse([wrong_clause_call]))
agent5 = ModificationAgent(wrong_clause_client)
try:
    agent5.generate_candidate(clause, None, ["延长试用期"])
    check(False, "clause_id 不一致时应该被拒绝")
except ModificationAgentError as exc:
    check("clause_id 与目标条款不一致" in str(exc), f"异常信息应说明 clause_id 不一致，实际：{exc}")

# 6. 底层 API 调用抛出 OpenAIError（网络失败等）
error_client = _FakeCompatibleClient(_FakeOpenAIError("模拟网络错误"))
agent6 = ModificationAgent(error_client)
try:
    agent6.generate_candidate(clause, None, ["延长试用期"])
    check(False, "底层调用失败时应该抛出 ModificationAgentError")
except ModificationAgentError as exc:
    check("调用 LLM 失败" in str(exc), f"异常信息应说明 LLM 调用失败，实际：{exc}")

print(f"\nALL {assertions} ASSERTIONS PASSED（替代测试：假 OpenAI 客户端，不是真实 LLM 调用）")
