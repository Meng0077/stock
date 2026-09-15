"""异步 HTTP 请求、模型时限和用量记录均用离线假客户端验证。"""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from stock_agent.llm_client import (
    LLMFunction as Function,
    LLMMessage as CompletionMessage,
    LLMToolCall as CompletionMessageToolCall,
)


def load_agent():
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_async", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


def configure_agent(monkeypatch, agent, *, api_key="fake-key", model="offline"):
    """给 main 注入离线 DeepSeek 配置，不读取真实 .env。"""
    config = SimpleNamespace(provider="deepseek", api_key=api_key, model=model)
    monkeypatch.setattr(agent, "get_llm_config", lambda path: config)
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "30")


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
        async with agent.LLMClient(
            provider="deepseek",
            api_key="fake-key",
            timeout=1,
            transport=httpx.MockTransport(respond),
        ) as client:
            return await client.create(model="offline", messages=[{"role": "user", "content": "hi"}])

    completion = asyncio.run(run())

    assert completion.choices[0].message.content == "{}"
    assert completion.usage.total_tokens == 5
    assert len(seen) == 1
    assert seen[0].url.path == "/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer fake-key"
    payload = json.loads(seen[0].content)
    assert payload["model"] == "offline"
    assert payload["thinking"] == {"type": "disabled"}


def test_model_request_timeout_stops_without_retry(capsys):
    agent = load_agent()
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0.05)

    events = []
    result = asyncio.run(agent.model_loop(
        SimpleNamespace(create=create), "offline",
        events=events, model_timeout=0.005,
    ))

    assert result == 1
    assert len(calls) == 1
    assert [event["type"] for event in events] == ["model_timeout", "run_finished"]
    assert events[-1]["error"]["code"] == "model_timeout"
    assert events[-1]["run_id"] == events[0]["run_id"]
    assert "模型请求超时" in capsys.readouterr().err


def test_task_timeout_propagates_without_model_timeout_event():
    agent = load_agent()

    async def create(**kwargs):
        await asyncio.sleep(0.05)

    events = []

    async def run():
        async with asyncio.timeout(0.005):
            await agent.model_loop(
                SimpleNamespace(create=create), "offline",
                events=events, model_timeout=1,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert events == []


def test_unexpected_model_error_propagates_to_safe_outer_boundary():
    agent = load_agent()

    async def create(**kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_ERROR")

    events = []
    with pytest.raises(RuntimeError, match="PRIVATE_PROVIDER_ERROR"):
        asyncio.run(
            agent.model_loop(
                SimpleNamespace(create=create),
                "offline",
                events=events,
            )
        )

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
        SimpleNamespace(create=create), "offline", events=events,
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
                SimpleNamespace(create=create), "offline",
                events=events, model_timeout=1,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert len(requests) == 2
    assert any(event["type"] == "tool_succeeded" for event in events)
    assert not any(event["type"] == "model_timeout" for event in events)


def test_http_status_error_is_reported_without_exposing_key(monkeypatch, capsys):
    agent = load_agent()
    configure_agent(monkeypatch, agent, api_key="PRIVATE_TEST_KEY")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "1")

    real_client_class = agent.LLMClient

    def fake_client(**kwargs):
        return real_client_class(
            **kwargs,
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
        )

    monkeypatch.setattr(agent, "LLMClient", fake_client)

    events = []
    assert asyncio.run(agent.main([], events=events)) == 1
    error = capsys.readouterr().err
    assert "模型服务返回错误状态" in error
    assert "PRIVATE_TEST_KEY" not in error
    assert events[-1]["error"]["code"] == "model_error"
    assert "PRIVATE_TEST_KEY" not in json.dumps(events)


def test_main_cancellation_closes_client_records_event_and_stops_work(monkeypatch):
    agent = load_agent()
    configure_agent(monkeypatch, agent)

    started = asyncio.Event()
    timeline = []

    class RecordedEvents(list):
        def append(self, event):
            timeline.append(event["type"])
            super().append(event)

    events = RecordedEvents()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            timeline.append("client_closed")

    async def fake_model_loop(*args, **kwargs):
        timeline.append("model_started")
        started.set()
        await asyncio.sleep(60)
        timeline.append("next_request")
        return 0

    monkeypatch.setattr(agent, "LLMClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(agent, "model_loop", fake_model_loop)

    async def run():
        task = asyncio.create_task(agent.main([], events=events))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(run())
    assert events[0] == {"type": "cancelled"}
    assert events[1]["type"] == "run_finished"
    assert events[1]["status"] == "cancelled"
    assert events[1]["error"]["code"] == "cancelled"
    assert timeline == ["model_started", "client_closed", "cancelled", "run_finished"]


def test_main_total_timeout_records_total_timeout_after_client_closes(monkeypatch):
    agent = load_agent()
    configure_agent(monkeypatch, agent)
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "300")
    monkeypatch.setattr(agent, "TASK_TIMEOUT_SECONDS", 0.005)
    closed = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            closed.append(True)

    async def wait_forever(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(agent, "LLMClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(agent, "model_loop", wait_forever)
    events = []

    assert asyncio.run(agent.main([], events=events)) == 1
    assert closed == [True]
    assert len(events) == 1
    assert events[0]["status"] == "failed"
    assert events[0]["error"]["code"] == "total_timeout"


def test_unrelated_timeout_is_not_labeled_total_timeout(monkeypatch):
    agent = load_agent()
    configure_agent(monkeypatch, agent)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass

    async def failing_loop(*args, **kwargs):
        raise TimeoutError("PRIVATE_PROVIDER_ERROR")

    monkeypatch.setattr(agent, "LLMClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(agent, "model_loop", failing_loop)
    events = []

    assert asyncio.run(agent.main([], events=events)) == 1
    assert events[0]["error"]["code"] == "model_error"
    assert "PRIVATE_PROVIDER_ERROR" not in json.dumps(events)


def test_client_close_error_replaces_success_terminal_event(monkeypatch):
    agent = load_agent()
    configure_agent(monkeypatch, agent)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")

    async def completed_loop(*args, events, **kwargs):
        agent.record_run_finished(events, "same-run", "completed")
        return 0

    monkeypatch.setattr(agent, "LLMClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(agent, "model_loop", completed_loop)
    events = []

    assert asyncio.run(agent.main([], events=events)) == 1
    assert len(events) == 1
    assert events[0]["run_id"] == "same-run"
    assert events[0]["status"] == "failed"
    assert events[0]["error"]["code"] == "model_error"
    assert "PRIVATE_PROVIDER_ERROR" not in json.dumps(events)
