"""统一 LLM 客户端的 provider、配置和响应适配测试。"""

import asyncio
import json

import httpx
import pytest

from stock_agent.llm_client import LLMClient, get_llm_config


def test_deepseek_request_uses_provider_url_and_disables_thinking():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_quote",
                                        "arguments": '{"company_id":"NVDA"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    async def run():
        async with LLMClient(
            provider="deepseek",
            api_key="fake-key",
            timeout=1,
            transport=httpx.MockTransport(respond),
        ) as client:
            return await client.create(
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": "hi"}],
            )

    completion = asyncio.run(run())
    payload = json.loads(seen[0].content)

    assert str(seen[0].url) == "https://api.deepseek.com/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer fake-key"
    assert payload["thinking"] == {"type": "disabled"}
    assert completion.choices[0].message.tool_calls[0].function.name == "get_quote"
    assert completion.usage.total_tokens == 5


def test_zhipu_request_does_not_add_deepseek_thinking_parameter():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "{}"},
                    }
                ]
            },
        )

    async def run():
        async with LLMClient(
            provider="zhipu",
            api_key="fake-key",
            timeout=1,
            transport=httpx.MockTransport(respond),
        ) as client:
            await client.create(model="offline", messages=[{"role": "user", "content": "hi"}])

    asyncio.run(run())

    assert str(seen[0].url) == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert "thinking" not in json.loads(seen[0].content)


@pytest.mark.parametrize(
    ("provider", "key_name", "key_value"),
    [
        ("deepseek", "DEEPSEEK_API_KEY", "deepseek-key"),
        ("zhipu", "ZHIPU_API_KEY", "zhipu-key"),
    ],
)
def test_config_selects_key_for_provider(
    monkeypatch,
    tmp_path,
    provider,
    key_name,
    key_value,
):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("MODEL_NAME", "offline-model")
    monkeypatch.setenv(key_name, key_value)

    config = get_llm_config(env_path)

    assert config.provider == provider
    assert config.api_key == key_value
    assert config.model == "offline-model"


def test_incomplete_or_unknown_config_returns_none(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    for name in (
        "LLM_PROVIDER",
        "MODEL_NAME",
        "DEEPSEEK_API_KEY",
        "ZHIPU_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    assert get_llm_config(env_path) is None

    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    monkeypatch.setenv("MODEL_NAME", "offline-model")
    assert get_llm_config(env_path) is None


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="不支持的 LLM provider"):
        LLMClient(provider="unknown", api_key="fake-key", timeout=1)
