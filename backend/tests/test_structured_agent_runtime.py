"""D04 入口与工具协议的离线失败路径。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from zai.types.chat.chat_completion import CompletionMessage, CompletionMessageToolCall, Function


def load_agent():
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_runtime", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


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

    def create(**kwargs):
        nonlocal request_count
        request_count += 1
        return response

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = []

    assert agent.model_loop(client, "offline", "fake-key", events=events) == 1
    assert request_count == 1
    assert events == []
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

        def create(**kwargs):
            requests.append(deepcopy(kwargs["messages"]))
            return responses[len(requests) - 1]

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return client, requests

    first_client, first_requests = make_client("first-call")
    second_client, second_requests = make_client("second-call")
    first_events, second_events = [], []

    assert agent.model_loop(first_client, "offline", "fake-key", events=first_events) == 0
    assert agent.model_loop(second_client, "offline", "fake-key", events=second_events) == 0

    assert agent.messages == initial_messages
    assert len(first_requests[0]) == len(second_requests[0]) == len(initial_messages)
    assert first_requests[1][-1]["tool_call_id"] == "first-call"
    assert second_requests[1][-1]["tool_call_id"] == "second-call"
    assert json.loads(first_requests[1][-1]["content"])["evidence_id"] == "E1"
    assert json.loads(second_requests[1][-1]["content"])["evidence_id"] == "E1"
    assert {event["run_id"] for event in first_events} != {event["run_id"] for event in second_events}


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
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))
    )

    assert agent.model_loop(client, "offline", "fake-key") == 1
    assert "证据校验失败" in capsys.readouterr().err


def test_main_returns_model_loop_status_and_closes_client(monkeypatch):
    agent = load_agent()
    monkeypatch.setattr(agent, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("ZHIPU_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_NAME", "offline")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "30")
    closed = []
    fake_client = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(agent, "ZhipuAiClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(agent, "model_loop", lambda *args: 1)

    assert agent.main([]) == 1
    assert closed == [True]


def test_client_creation_failure_is_safe_and_returns_failure(monkeypatch, capsys):
    agent = load_agent()
    monkeypatch.setattr(agent, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("ZHIPU_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_NAME", "offline")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "30")

    def fail_client(**kwargs):
        raise RuntimeError("sensitive-provider-detail")

    monkeypatch.setattr(agent, "ZhipuAiClient", fail_client)

    assert agent.main([]) == 1
    assert "sensitive-provider-detail" not in capsys.readouterr().err
