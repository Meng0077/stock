"""公共工具调用模块不能把一次运行的状态写入另一次运行。"""

import json

import pytest
from zai.types.chat.chat_completion import CompletionMessage, CompletionMessageToolCall, Function

from stock_agent.agents.tool_calling import ToolCallProtocolError, execute_tool_and_return


def tool_message(*call_ids: str) -> CompletionMessage:
    return CompletionMessage(
        role="assistant",
        tool_calls=[
            CompletionMessageToolCall(
                id=call_id,
                type="function",
                function=Function(name="get_quote", arguments='{"company_id":"NVDA"}'),
            )
            for call_id in call_ids
        ],
    )


def test_tool_return_uses_only_the_given_run_state():
    first_messages, first_events = [], []
    second_messages, second_events = [], []

    first_count = execute_tool_and_return(
        tool_message("first-call"),
        messages=first_messages,
        events=first_events,
        run_id="first-run",
        tool_calls_executed=0,
        max_tools=2,
    )
    second_count = execute_tool_and_return(
        tool_message("second-call"),
        messages=second_messages,
        events=second_events,
        run_id="second-run",
        tool_calls_executed=0,
        max_tools=2,
    )

    assert first_count == second_count == 1
    assert [message["tool_call_id"] for message in first_messages if message["role"] == "tool"] == ["first-call"]
    assert [message["tool_call_id"] for message in second_messages if message["role"] == "tool"] == ["second-call"]
    assert {event["run_id"] for event in first_events} == {"first-run"}
    assert {event["run_id"] for event in second_events} == {"second-run"}
    assert json.loads(first_messages[-1]["content"])["ok"] is True


def test_duplicate_tool_ids_leave_run_state_untouched():
    messages, events = [], []

    with pytest.raises(ToolCallProtocolError, match="重复"):
        execute_tool_and_return(
            tool_message("duplicate", "duplicate"),
            messages=messages,
            events=events,
            run_id="run-id",
            tool_calls_executed=0,
            max_tools=2,
        )

    assert messages == []
    assert events == []
