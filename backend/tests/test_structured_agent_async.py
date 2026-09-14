"""异步 HTTP 请求、模型时限和用量记录均用离线假客户端验证。"""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from zai.types.chat.chat_completion import CompletionMessage, CompletionMessageToolCall, Function


def load_agent():
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_async", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


def test_async_http_client_posts_authenticated_json_without_network():
    agent = load_agent()
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "{}"},
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        })

    async def run():
        async with agent.BigModelAsyncClient(
            api_key="fake-key", timeout=1, transport=httpx.MockTransport(respond)
        ) as client:
            return await client.create(model="offline", messages=[{"role": "user", "content": "hi"}])

    completion = asyncio.run(run())

    assert completion.choices[0].message.content == "{}"
    assert completion.usage.total_tokens == 5
    assert len(seen) == 1
    assert seen[0].url.path == "/api/paas/v4/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer fake-key"
    assert json.loads(seen[0].content)["model"] == "offline"


def test_model_request_timeout_stops_without_retry(capsys):
    agent = load_agent()
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0.05)

    events = []
    result = asyncio.run(agent.model_loop(
        SimpleNamespace(create=create), "offline", "fake-key",
        events=events, model_timeout=0.005,
    ))

    assert result == 1
    assert len(calls) == 1
    assert [event["type"] for event in events] == ["model_timeout"]
    assert "模型请求超时" in capsys.readouterr().err


def test_task_timeout_propagates_without_model_timeout_event():
    agent = load_agent()

    async def create(**kwargs):
        await asyncio.sleep(0.05)

    events = []

    async def run():
        async with asyncio.timeout(0.005):
            await agent.model_loop(
                SimpleNamespace(create=create), "offline", "fake-key",
                events=events, model_timeout=1,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert events == []


def test_model_usage_is_recorded_for_the_request():
    agent = load_agent()
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant", tool_calls=None, content=(
                        '{"status":"insufficient_information","facts":[],"inferences":[],'
                        '"missing_information":["缺少资料"],"data_mode":"fixture"}'
                    ),
                ),
            )],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=6, total_tokens=10),
        )

    events = []
    result = asyncio.run(agent.model_loop(
        SimpleNamespace(create=create), "offline", "fake-key", events=events,
    ))

    assert result == 0
    assert requests[0]["max_tokens"] == agent.MAX_OUTPUT_TOKENS
    assert events[0]["type"] == "model_usage"
    assert events[0]["round"] == 1
    assert events[0]["usage"] == {
        "prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10,
    }


def test_total_timeout_stops_after_second_model_request():
    agent = load_agent()
    tool_call = CompletionMessageToolCall(
        id="quote-call",
        type="function",
        function=Function(name="get_quote", arguments='{"company_id":"NVDA"}'),
    )
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    finish_reason="tool_calls",
                    message=CompletionMessage(role="assistant", tool_calls=[tool_call]),
                )],
                usage=None,
            )
        await asyncio.sleep(0.05)

    events = []

    async def run():
        async with asyncio.timeout(0.005):
            await agent.model_loop(
                SimpleNamespace(create=create), "offline", "fake-key",
                events=events, model_timeout=1,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert len(requests) == 2
    assert any(event["type"] == "tool_succeeded" for event in events)
    assert not any(event["type"] == "model_timeout" for event in events)


def test_http_status_error_is_reported_without_exposing_key(monkeypatch, capsys):
    agent = load_agent()
    monkeypatch.setattr(agent, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("ZHIPU_API_KEY", "PRIVATE_TEST_KEY")
    monkeypatch.setenv("MODEL_NAME", "offline")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "1")

    real_client_class = agent.BigModelAsyncClient

    def fake_client(**kwargs):
        return real_client_class(
            **kwargs,
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
        )

    monkeypatch.setattr(agent, "BigModelAsyncClient", fake_client)

    assert asyncio.run(agent.main([])) == 1
    error = capsys.readouterr().err
    assert "模型服务返回错误状态" in error
    assert "PRIVATE_TEST_KEY" not in error
