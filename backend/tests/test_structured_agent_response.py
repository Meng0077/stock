"""D04 Task 2：不完整响应和拒答不能进入格式修复。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from zai.types.chat.chat_completion import CompletionMessage, CompletionMessageToolCall, Function


VALID_OUTPUT = (
    '{"status":"insufficient_information","facts":[],"inferences":[],'
    '"missing_information":["缺少资料"],"data_mode":"fixture"}'
)


def load_agent():
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_response", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


def run_once(choice, *, events=None):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[] if choice is None else [choice], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = load_agent().model_loop(client, "offline", "fake-key", events=events)
    return result, calls


@pytest.mark.parametrize(
    "choice",
    [
        None,
        SimpleNamespace(message=CompletionMessage(role="assistant", content=""), finish_reason="stop"),
        SimpleNamespace(message=CompletionMessage(role="assistant", content="  "), finish_reason="stop"),
        SimpleNamespace(message=CompletionMessage(role="assistant", content=VALID_OUTPUT), finish_reason="length"),
    ],
    ids=["no-choices", "empty-content", "whitespace-content", "truncated"],
)
def test_incomplete_answer_fails_without_repair(choice):
    result, calls = run_once(choice)

    assert result == 1
    assert len(calls) == 1


def test_plain_text_refusal_fails_without_repair(capsys):
    choice = SimpleNamespace(
        message=CompletionMessage(role="assistant", content="抱歉，我不能提供这项分析。"),
        finish_reason="stop",
    )

    result, calls = run_once(choice)

    assert result == 1
    assert len(calls) == 1
    assert "模型拒答" in capsys.readouterr().err


def test_explicit_refusal_marker_fails_without_repair():
    choice = SimpleNamespace(
        message=SimpleNamespace(content=VALID_OUTPUT, tool_calls=None, refusal="blocked"),
        finish_reason="stop",
    )

    result, calls = run_once(choice)

    assert result == 1
    assert len(calls) == 1


def test_truncated_tool_call_is_not_executed():
    tool_call = CompletionMessageToolCall(
        id="partial-call",
        type="function",
        function=Function(name="get_quote", arguments='{"company_id":"NVDA"}'),
    )
    choice = SimpleNamespace(
        message=CompletionMessage(role="assistant", tool_calls=[tool_call]),
        finish_reason="length",
    )
    events = []

    result, calls = run_once(choice, events=events)

    assert result == 1
    assert len(calls) == 1
    assert events == []
