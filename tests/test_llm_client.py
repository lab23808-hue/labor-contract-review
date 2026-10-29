"""llm/client.py 的单元测试。运行：在项目根目录执行 `pytest`。

只验证 wiring（参数有没有传对、异常有没有被正确包装），不会真正请求网络：
用 unittest.mock.patch 替换掉 llm.client.OpenAI 这个类，而不是依赖任何自造的假
openai 模块——这样无论本地装的是真的 openai SDK 还是别的什么，测试行为都一致，
也绝不会真的发起网络请求。
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from openai import OpenAIError

from infra.llm.client import (
    DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    LLMClientError,
    OpenAICompatibleClient,
    build_deepseek_client,
)


def _mock_response(content):
    """构造一个形状和真实 openai ChatCompletion 响应一致的假响应对象。"""
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


def _with_env(**env_vars):
    """临时设置/删除环境变量（value 为 None 表示删除），返回一个还原函数。"""
    saved = {key: os.environ.get(key) for key in env_vars}

    def restore():
        for key, old_value in saved.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value

    for key, value in env_vars.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return restore


# ---------- OpenAICompatibleClient ----------

def test_chat_returns_message_content():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.chat.completions.create.return_value = _mock_response("你好")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        result = client.chat([{"role": "user", "content": "hi"}])

    assert result == "你好"


def test_chat_passes_model_and_messages_and_temperature():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_create = mock_openai_cls.return_value.chat.completions.create
        mock_create.return_value = _mock_response("ok")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        client.chat([{"role": "user", "content": "hi"}], temperature=0.3)

        _, kwargs = mock_create.call_args
    assert kwargs["model"] == "my-model"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["temperature"] == 0.3
    assert kwargs["timeout"] == 60


def test_chat_default_temperature_is_zero():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_create = mock_openai_cls.return_value.chat.completions.create
        mock_create.return_value = _mock_response("ok")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        client.chat([{"role": "user", "content": "hi"}])

        _, kwargs = mock_create.call_args
    assert kwargs["temperature"] == 0.0


def test_chat_json_mode_sets_response_format():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_create = mock_openai_cls.return_value.chat.completions.create
        mock_create.return_value = _mock_response("{}")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        client.chat([{"role": "user", "content": "hi"}], json_mode=True)

        _, kwargs = mock_create.call_args
    assert kwargs["response_format"] == {"type": "json_object"}


def test_chat_without_json_mode_does_not_set_response_format():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_create = mock_openai_cls.return_value.chat.completions.create
        mock_create.return_value = _mock_response("ok")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        client.chat([{"role": "user", "content": "hi"}])

        _, kwargs = mock_create.call_args
    assert "response_format" not in kwargs


def test_client_is_constructed_with_given_api_key_and_base_url():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        OpenAICompatibleClient(api_key="k-123", base_url="https://custom.example.com", model="m")

        _, kwargs = mock_openai_cls.call_args
    assert kwargs["api_key"] == "k-123"
    assert kwargs["base_url"] == "https://custom.example.com"


def test_chat_wraps_api_errors():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.chat.completions.create.side_effect = OpenAIError("限流了")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        with pytest.raises(LLMClientError):
            client.chat([{"role": "user", "content": "hi"}])


def test_chat_rejects_empty_content():
    with patch("infra.llm.client.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.chat.completions.create.return_value = _mock_response("")
        client = OpenAICompatibleClient(api_key="k", base_url="https://example.com", model="my-model")

        with pytest.raises(LLMClientError):
            client.chat([{"role": "user", "content": "hi"}])


# ---------- build_deepseek_client ----------

def test_build_deepseek_client_uses_env_vars():
    restore = _with_env(DEEPSEEK_API_KEY="sk-test", DEEPSEEK_MODEL="deepseek-v4-pro")
    try:
        with patch("infra.llm.client.load_dotenv"), patch("infra.llm.client.OpenAI") as mock_openai_cls:
            client = build_deepseek_client()
            _, kwargs = mock_openai_cls.call_args
        assert client.model == "deepseek-v4-pro"
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["base_url"] == DEEPSEEK_BASE_URL
    finally:
        restore()


def test_build_deepseek_client_defaults_model_when_not_set():
    restore = _with_env(DEEPSEEK_API_KEY="sk-test", DEEPSEEK_MODEL=None)
    try:
        with patch("infra.llm.client.load_dotenv"), patch("infra.llm.client.OpenAI"):
            client = build_deepseek_client()
        assert client.model == DEFAULT_DEEPSEEK_MODEL
    finally:
        restore()


def test_build_deepseek_client_explicit_model_overrides_env():
    restore = _with_env(DEEPSEEK_API_KEY="sk-test", DEEPSEEK_MODEL="deepseek-v4-pro")
    try:
        with patch("infra.llm.client.load_dotenv"), patch("infra.llm.client.OpenAI"):
            client = build_deepseek_client(model="deepseek-v4-flash")
        assert client.model == "deepseek-v4-flash"
    finally:
        restore()


def test_build_deepseek_client_missing_api_key_raises():
    # 必须把 load_dotenv 也 mock 掉：否则本地真实的 .env 文件（跑验证脚本需要
    # 它）会在 build_deepseek_client() 内部被重新读取，把刚删除的环境变量
    # 又补回去，导致这个"缺 key 应该报错"的用例测不出问题。
    restore = _with_env(DEEPSEEK_API_KEY=None)
    try:
        with patch("infra.llm.client.load_dotenv"):
            with pytest.raises(LLMClientError):
                build_deepseek_client()
    finally:
        restore()
