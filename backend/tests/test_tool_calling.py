"""公共工具调用模块不能把一次运行的状态写入另一次运行。"""

import asyncio
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

    first_count = asyncio.run(execute_tool_and_return(
        tool_message("first-call"),
        messages=first_messages,
        events=first_events,
        run_id="first-run",
        tool_calls_executed=0,
        max_tools=2,
    ))
    second_count = asyncio.run(execute_tool_and_return(
        tool_message("second-call"),
        messages=second_messages,
        events=second_events,
        run_id="second-run",
        tool_calls_executed=0,
        max_tools=2,
    ))

    assert first_count == second_count == 1
    assert [message["tool_call_id"] for message in first_messages if message["role"] == "tool"] == ["first-call"]
    assert [message["tool_call_id"] for message in second_messages if message["role"] == "tool"] == ["second-call"]
    assert {event["run_id"] for event in first_events} == {"first-run"}
    assert {event["run_id"] for event in second_events} == {"second-run"}
    assert json.loads(first_messages[-1]["content"])["ok"] is True
    assert "evidence_id" not in json.loads(first_messages[-1]["content"])


def test_evidence_ids_are_unique_and_only_assigned_to_successful_results():
    calls = [
        CompletionMessageToolCall(
            id=call_id,
            type="function",
            function=Function(name=name, arguments=arguments),
        )
        for call_id, name, arguments in [
            ("quote", "get_quote", '{"company_id":"NVDA"}'),
            ("bad", "get_quote", "not-json"),
            ("profile", "get_company_profile", '{"company_id":"NVDA"}'),
        ]
    ]
    messages, events, allowed_ids = [], [], set()

    count = asyncio.run(execute_tool_and_return(
        CompletionMessage(role="assistant", tool_calls=calls),
        messages=messages,
        events=events,
        run_id="run-id",
        tool_calls_executed=0,
        max_tools=3,
        allowed_ids=allowed_ids,
    ))

    tool_messages = [message for message in messages if message["role"] == "tool"]
    results = [json.loads(message["content"]) for message in tool_messages]
    assert count == 2
    assert [result.get("evidence_id") for result in results] == ["E1", None, "E2"]
    assert allowed_ids == {"E1", "E2"}


def test_duplicate_tool_ids_leave_run_state_untouched():
    messages, events = [], []

    with pytest.raises(ToolCallProtocolError, match="重复"):
        asyncio.run(execute_tool_and_return(
            tool_message("duplicate", "duplicate"),
            messages=messages,
            events=events,
            run_id="run-id",
            tool_calls_executed=0,
            max_tools=2,
        ))

    assert messages == []
    assert events == []


def test_local_tool_timeout_returns_tool_error(monkeypatch):
    from stock_agent.agents import tool_calling

    async def slow_tool(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {"company_id": "NVDA", "data_mode": "fixture"}

    monkeypatch.setattr(tool_calling, "execute_tool", slow_tool)
    monkeypatch.setattr(tool_calling, "TOOL_TIMEOUT_SECONDS", 0.005)
    messages, events = [], []

    count = asyncio.run(execute_tool_and_return(
        tool_message("slow-call"),
        messages=messages,
        events=events,
        run_id="run-id",
        tool_calls_executed=0,
        max_tools=1,
    ))

    assert count == 0
    assert json.loads(messages[-1]["content"]) == {
        "ok": False,
        "error": {"code": "tool_timeout", "message": "工具调用超时。"},
    }
    assert events[-1]["type"] == "tool_failed"
    assert events[-1]["code"] == "tool_timeout"


def test_total_timeout_is_not_rewritten_as_tool_timeout(monkeypatch):
    from stock_agent.agents import tool_calling

    async def slow_tool(*args, **kwargs):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(tool_calling, "execute_tool", slow_tool)
    monkeypatch.setattr(tool_calling, "TOOL_TIMEOUT_SECONDS", 1)
    messages, events = [], []

    async def run():
        async with asyncio.timeout(0.005):
            await execute_tool_and_return(
                tool_message("slow-call"),
                messages=messages,
                events=events,
                run_id="run-id",
                tool_calls_executed=0,
                max_tools=1,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert not any(event.get("code") == "tool_timeout" for event in events)
    assert not any(message.get("role") == "tool" for message in messages)


def test_total_timeout_does_not_start_remaining_tool_calls(monkeypatch):
    from stock_agent.agents import tool_calling

    started = []

    async def slow_tool(*args, **kwargs):
        started.append(True)
        await asyncio.sleep(0.05)
        return {"company_id": "NVDA", "data_mode": "fixture"}

    monkeypatch.setattr(tool_calling, "execute_tool", slow_tool)
    monkeypatch.setattr(tool_calling, "TOOL_TIMEOUT_SECONDS", 1)
    messages, events = [], []

    async def run():
        async with asyncio.timeout(0.005):
            await execute_tool_and_return(
                tool_message("first", "second"),
                messages=messages,
                events=events,
                run_id="run-id",
                tool_calls_executed=0,
                max_tools=2,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert started == [True]
    assert not any(message.get("role") == "tool" for message in messages)
