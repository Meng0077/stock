"""D04 入口与工具协议的离线失败路径。"""

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from stock_agent.llm_client import (
    LLMFunction as Function,
    LLMMessage as CompletionMessage,
    LLMToolCall as CompletionMessageToolCall,
)


def load_agent():
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_runtime", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


def test_cli_reuses_packaged_model_loop():
    agent = load_agent()

    assert agent.model_loop.__module__ == "stock_agent.agents.manual_agent"


def configure_agent(monkeypatch, agent):
    """给 main 注入离线 DeepSeek 配置，不读取真实 .env。"""
    config = SimpleNamespace(
        provider="deepseek",
        api_key="fake-key",
        model="offline",
    )
    monkeypatch.setattr(agent, "get_llm_config", lambda path: config)
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "30")


def test_duplicate_tool_id_stops_without_retry_or_mutating_template(capsys):
    agent = load_agent()
    initial_messages = deepcopy(agent.messages)
    calls = [
        CompletionMessageToolCall(
            id="duplicate",
            type="function",
            function=Function(name="get_quote", arguments='{"company_id":"NVDA"}'),
        )
        for _ in range(2)
    ]
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=CompletionMessage(role="assistant", tool_calls=calls),
            finish_reason="tool_calls",
        )],
        usage=None,
    )
    request_count = 0

    async def create(**kwargs):
        nonlocal request_count
        request_count += 1
        return response

    client = SimpleNamespace(create=create)
    events = []

    assert asyncio.run(agent.model_loop(client, "offline", events=events)) == 1
    assert request_count == 1
    assert len(events) == 1
    assert events[0]["type"] == "run_finished"
    assert events[0]["error"]["code"] == "invalid_tool_call"
    assert agent.messages == initial_messages
    assert "工具调用协议错误" in capsys.readouterr().err


def test_two_runs_keep_tool_messages_and_events_separate():
    agent = load_agent()
    initial_messages = deepcopy(agent.messages)
    final_json = (
        '{"status":"completed","facts":[{"text":"已取得报价","evidence_ids":["E1"]}],'
        '"inferences":[],"missing_information":[],"data_mode":"fixture"}'
    )

    def make_client(call_id):
        tool_call = CompletionMessageToolCall(
            id=call_id,
            type="function",
            function=Function(name="get_quote", arguments='{"company_id":"NVDA"}'),
        )
        responses = [
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=CompletionMessage(role="assistant", tool_calls=[tool_call]),
                    finish_reason="tool_calls",
                )],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=CompletionMessage(role="assistant", content=final_json),
                    finish_reason="stop",
                )],
                usage=None,
            ),
        ]
        requests = []

        async def create(**kwargs):
            requests.append(deepcopy(kwargs["messages"]))
            return responses[len(requests) - 1]

        client = SimpleNamespace(create=create)
        return client, requests

    first_client, first_requests = make_client("first-call")
    second_client, second_requests = make_client("second-call")
    first_events, second_events = [], []

    assert asyncio.run(agent.model_loop(first_client, "offline", events=first_events)) == 0
    assert asyncio.run(agent.model_loop(second_client, "offline", events=second_events)) == 0

    assert agent.messages == initial_messages
    assert len(first_requests[0]) == len(second_requests[0]) == len(initial_messages)
    assert first_requests[1][-1]["tool_call_id"] == "first-call"
    assert second_requests[1][-1]["tool_call_id"] == "second-call"
    assert json.loads(first_requests[1][-1]["content"])["evidence_id"] == "E1"
    assert json.loads(second_requests[1][-1]["content"])["evidence_id"] == "E1"
    assert {event["run_id"] for event in first_events} != {event["run_id"] for event in second_events}
    assert first_events[-1]["status"] == second_events[-1]["status"] == "completed"
    assert not any("error" in event for event in (first_events[-1], second_events[-1]))


def test_final_answer_rejects_evidence_not_provided_in_this_run(capsys):
    agent = load_agent()
    final_json = (
        '{"status":"completed","facts":[{"text":"已取得报价","evidence_ids":["E99"]}],'
        '"inferences":[],"missing_information":[],"data_mode":"fixture"}'
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=CompletionMessage(role="assistant", content=final_json),
            finish_reason="stop",
        )],
        usage=None,
    )
    async def create(**kwargs):
        return response

    client = SimpleNamespace(create=create)

    assert asyncio.run(agent.model_loop(client, "offline")) == 1
    assert "证据校验失败" in capsys.readouterr().err


def test_main_returns_model_loop_status_and_closes_client(monkeypatch):
    agent = load_agent()
    configure_agent(monkeypatch, agent)
    closed = []
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            closed.append(True)

    async def fake_model_loop(*args, **kwargs):
        return 1

    monkeypatch.setattr(agent, "LLMClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(agent, "model_loop", fake_model_loop)

    assert asyncio.run(agent.main([])) == 1
    assert closed == [True]


def test_client_creation_failure_is_safe_and_returns_failure(monkeypatch, capsys):
    agent = load_agent()
    configure_agent(monkeypatch, agent)

    def fail_client(**kwargs):
        raise RuntimeError("sensitive-provider-detail")

    monkeypatch.setattr(agent, "LLMClient", fail_client)

    assert asyncio.run(agent.main([])) == 1
    assert "sensitive-provider-detail" not in capsys.readouterr().err
