"""D07 Step 8：最小 LangChain Agent 的离线契约与工具轨迹测试。"""

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from pydantic import Field

from stock_agent.agents.langchain import langchain_agent, langchain_tools, tool_middleware
from stock_agent.agents.langchain.langchain_agent import (
    SYSTEM_PROMPT,
    build_agent_input,
    build_langchain_agent,
    invoke_langchain_agent,
    run_research,
)
from stock_agent.agents.langchain.langchain_tools import build_langchain_tools
from stock_agent.agents.structured_output import collect_evidence_ids, validate_evidence
from stock_agent.schemas.research import ResearchRequest
from stock_agent.schemas.research_output import ResearchOutput
from stock_agent.schemas.errors import make_public_error
from stock_agent.tools.registry import TOOL_REGISTRY


class ToolCallingFakeModel(FakeMessagesListChatModel):
    """依次返回预设 AIMessage，并记录 Agent 实际绑定的工具名。"""

    bound_tool_names: list[str] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs: Any):
        self.bound_tool_names = [tool.name for tool in tools]
        return self


@pytest.fixture
def research_request() -> ResearchRequest:
    return ResearchRequest(
        company_id="NVDA",
        question="查询教学模拟报价",
        data_mode="fixture",
        as_of="2026-09-15T16:00:00+08:00",
    )


def test_build_agent_input_serializes_all_request_fields(research_request):
    state = build_agent_input(research_request)

    assert list(state) == ["messages"]
    assert [message["role"] for message in state["messages"]] == ["user"]
    assert json.loads(state["messages"][0]["content"]) == {
        "company_id": "NVDA",
        "question": "查询教学模拟报价",
        "data_mode": "fixture",
        "as_of": "2026-09-15T16:00:00+08:00",
    }


def test_build_agent_uses_internal_tools_and_system_prompt(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(langchain_agent, "create_agent", fake_create_agent)

    assert build_langchain_agent("offline-model") is sentinel
    middleware = captured.pop("middleware")
    assert len(middleware) == 3
    assert middleware[0] is tool_middleware.handle_tool_errors
    assert isinstance(middleware[1], ModelCallLimitMiddleware)
    assert middleware[1].run_limit == langchain_agent.MAX_MODEL_ROUNDS
    assert isinstance(middleware[2], ToolCallLimitMiddleware)
    assert middleware[2].run_limit == langchain_agent.MAX_TOOL_CALLS
    assert captured == {
        "model": "offline-model",
        "tools": build_langchain_tools(),
        "system_prompt": SYSTEM_PROMPT,
        "response_format": None,
    }


def test_fake_model_completes_real_langchain_tool_loop(research_request):
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_quote",
                        "args": {"company_id": "NVDA"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="NVDA 教学模拟报价为 100 USD，不是实时行情。"),
        ]
    )
    agent = build_langchain_agent(model)

    state = asyncio.run(invoke_langchain_agent(agent, research_request))
    messages = state["messages"]

    assert model.bound_tool_names == ["get_quote", "get_company_profile"]
    assert [type(message) for message in messages] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert messages[1].tool_calls[0]["name"] == "get_quote"
    assert messages[2].name == "get_quote"
    assert messages[2].tool_call_id == "call-1"
    tool_result = json.loads(messages[2].content)
    assert tool_result.pop("evidence_id").startswith("E-")
    assert tool_result == {
        "company_id": "NVDA",
        "price": 100.0,
        "currency": "USD",
        "quoted_at": "2026-09-11T09:00:00+08:00",
        "data_mode": "fixture",
        "source": "本地教学模拟数据",
        "note": "固定虚构报价，仅用于验证工具调用；报价时间也是预设的教学时间。",
    }
    assert messages[3].tool_calls == []


@pytest.mark.parametrize("tool_name", ["get_quote", "get_company_profile"])
def test_unsupported_company_can_return_insufficient_information(tool_name):
    request = ResearchRequest(
        company_id="TSLA",
        question="查询教学模拟资料",
        data_mode="fixture",
        as_of="2026-09-15T16:00:00+08:00",
    )
    output_data = {
        "status": "insufficient_information",
        "facts": [],
        "inferences": [],
        "missing_information": ["当前仅支持 NVDA，缺少 TSLA 的教学模拟资料。"],
        "data_mode": "fixture",
    }
    model = ToolCallingFakeModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": tool_name,
            "args": {"company_id": "TSLA"},
            "id": "call-tsla",
        }]),
        AIMessage(content="", tool_calls=[{
            "name": "ResearchOutput",
            "args": output_data,
            "id": "call-output",
        }]),
    ])
    agent = build_langchain_agent(model, response_format=ToolStrategy(ResearchOutput))

    result = asyncio.run(invoke_langchain_agent(agent, request))
    tool_message = result["messages"][2]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.name == tool_name
    assert tool_message.status == "error"
    assert "不支持的公司标识：TSLA" in tool_message.content
    assert json.loads(tool_message.content)["error"]["code"] == "tool_rejected"
    assert "evidence_id" not in tool_message.content
    output = result["structured_response"]
    assert output.model_dump() == output_data
    allowed_ids = collect_evidence_ids(result["messages"])
    assert allowed_ids == set()
    assert validate_evidence(output, allowed_ids, request.data_mode) is output


@pytest.mark.parametrize("error_type", [ValueError, TypeError, RuntimeError, TimeoutError])
def test_unexpected_tool_errors_still_propagate(monkeypatch, research_request, error_type):
    def broken_handler(company_id):
        raise error_type("unexpected handler failure")

    monkeypatch.setitem(TOOL_REGISTRY["get_quote"], "handler", broken_handler)
    model = ToolCallingFakeModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "get_quote",
        "args": {"company_id": "NVDA"},
        "id": "call-broken",
    }])])
    agent = build_langchain_agent(model)

    with pytest.raises(error_type, match="unexpected handler failure"):
        asyncio.run(invoke_langchain_agent(agent, research_request))


@pytest.mark.parametrize("tool_name", ["get_quote", "get_company_profile"])
@pytest.mark.parametrize("arguments", [
    {},
    {"company_id": ""},
    {"company_id": 123},
    {"company_id": "NVDA", "extra": True},
])
def test_invalid_tool_arguments_return_error_without_handler(
    monkeypatch, research_request, tool_name, arguments,
):
    def unexpected_handler(company_id):
        raise AssertionError("参数校验失败时不应执行 handler")

    monkeypatch.setitem(TOOL_REGISTRY[tool_name], "handler", unexpected_handler)
    model = ToolCallingFakeModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": tool_name, "args": arguments, "id": "call-invalid",
        }]),
        AIMessage(content="工具参数错误，未获得资料。"),
    ])
    agent = build_langchain_agent(model)

    result = asyncio.run(invoke_langchain_agent(agent, research_request))
    message = result["messages"][2]
    assert isinstance(message, ToolMessage)
    assert message.name == tool_name
    assert message.tool_call_id == "call-invalid"
    assert message.status == "error"
    assert result["messages"][-1].content == "工具参数错误，未获得资料。"
    assert collect_evidence_ids(result["messages"]) == set()


@pytest.mark.parametrize("tool_name", ["get_quote", "get_company_profile"])
def test_tool_deadline_returns_error_and_cancels_handler(
    monkeypatch, research_request, tool_name,
):
    cancelled = []

    async def slow_handler(company_id):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(company_id)

    monkeypatch.setattr(tool_middleware, "TOOL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setitem(TOOL_REGISTRY[tool_name], "handler", slow_handler)
    model = ToolCallingFakeModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": tool_name, "args": {"company_id": "NVDA"}, "id": "call-slow",
        }]),
        AIMessage(content="工具超时，缺少所需资料。"),
    ])
    agent = build_langchain_agent(model)

    result = asyncio.run(invoke_langchain_agent(agent, research_request))
    message = result["messages"][2]
    assert message.status == "error"
    assert message.name == tool_name
    assert message.tool_call_id == "call-slow"
    assert json.loads(message.content)["error"]["code"] == "tool_timeout"
    assert cancelled == ["NVDA"]
    assert result["messages"][-1].content == "工具超时，缺少所需资料。"
    assert collect_evidence_ids(result["messages"]) == set()


@pytest.mark.parametrize("error_type", [
    httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout,
])
def test_tool_http_timeout_returns_safe_error(monkeypatch, research_request, error_type):
    async def timeout_handler(company_id):
        raise error_type("internal request details")

    monkeypatch.setitem(TOOL_REGISTRY["get_quote"], "handler", timeout_handler)
    model = ToolCallingFakeModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "get_quote", "args": {"company_id": "NVDA"}, "id": "call-http",
        }]),
        AIMessage(content="数据请求超时，缺少所需资料。"),
    ])
    agent = build_langchain_agent(model)

    result = asyncio.run(invoke_langchain_agent(agent, research_request))
    message = result["messages"][2]
    assert message.status == "error"
    assert json.loads(message.content)["error"]["code"] == "tool_timeout"
    assert "internal request details" not in message.content
    assert collect_evidence_ids(result["messages"]) == set()


def test_run_cancellation_is_not_converted_to_tool_error(monkeypatch, research_request):
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def waiting_handler(company_id):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setitem(TOOL_REGISTRY["get_quote"], "handler", waiting_handler)
        model = ToolCallingFakeModel(responses=[AIMessage(content="", tool_calls=[{
            "name": "get_quote", "args": {"company_id": "NVDA"}, "id": "call-cancel",
        }])])
        agent = build_langchain_agent(model)
        task = asyncio.create_task(invoke_langchain_agent(agent, research_request))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(run())


def test_fake_model_unknown_tool_has_no_execute_path(monkeypatch, research_request):
    async def unexpected_execute_tool(tool_name, arguments):
        raise AssertionError(f"未知工具不应执行：{tool_name} {arguments}")

    monkeypatch.setattr(
        langchain_tools,
        "execute_tool",
        unexpected_execute_tool,
    )
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "delete_file",
                        "args": {},
                        "id": "call-unknown",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="无法使用未授权工具。"),
        ]
    )
    agent = build_langchain_agent(model)

    state = asyncio.run(invoke_langchain_agent(agent, research_request))
    tool_message = state["messages"][2]

    assert isinstance(tool_message, ToolMessage)
    assert tool_message.name == "delete_file"
    assert tool_message.status == "error"


def test_invoke_returns_raw_state_without_d09_conversion(research_request):
    raw_state = {"messages": [AIMessage(content="raw")], "custom": object()}

    class FakeAgent:
        async def ainvoke(self, state):
            assert state == build_agent_input(research_request)
            return raw_state

    result = asyncio.run(invoke_langchain_agent(FakeAgent(), research_request))

    assert result is raw_state
    assert "structured_response" not in result


def test_module_imports_no_model_client_or_runtime_config_loader():
    assert not hasattr(langchain_agent, "ChatDeepSeek")
    assert not hasattr(langchain_agent, "get_llm_config")
    assert not hasattr(langchain_agent, "AgentRunResult")
    assert not hasattr(langchain_agent, "ResearchOutput")


@pytest.fixture
def research_state():
    return {
        "messages": [
            AIMessage(content="", tool_calls=[{
                "name": "get_quote",
                "args": {"company_id": "NVDA"},
                "id": "call-quote",
            }]),
            ToolMessage(
                content=json.dumps({"evidence_id": "E-quote"}),
                name="get_quote",
                tool_call_id="call-quote",
            ),
        ],
        "structured_response": ResearchOutput(
            status="completed",
            facts=[{"text": "教学模拟报价为 100 USD", "evidence_ids": ["E-quote"]}],
            inferences=[],
            missing_information=[],
            data_mode="fixture",
        ),
    }


@pytest.mark.parametrize("status", ["completed", "insufficient_information"])
def test_run_research_returns_output_identity_and_events(
    research_request, research_state, status,
):
    if status == "insufficient_information":
        research_state["structured_response"] = ResearchOutput(
            status=status,
            facts=[],
            inferences=[],
            missing_information=["缺少公司资料"],
            data_mode="fixture",
        )

    class FakeAgent:
        async def astream(self, state, *, stream_mode):
            assert state == build_agent_input(research_request)
            assert stream_mode == "values"
            yield research_state

    result = asyncio.run(run_research(FakeAgent(), research_request))

    assert set(result) == {"run_id", "status", "output", "error", "events"}
    UUID(result["run_id"])
    assert result["status"] == status
    assert result["output"] is research_state["structured_response"]
    assert result["error"] is None
    assert [event["type"] for event in result["events"]] == [
        "run_started", "tool_requested", "tool_succeeded", "run_finished",
    ]
    assert all(event["run_id"] == result["run_id"] for event in result["events"])
    assert result["events"][-1]["status"] == status


@pytest.mark.parametrize("change, code", [
    ({"facts": [{"text": "虚构引用", "evidence_ids": ["E-unknown"]}]}, "invalid_evidence"),
    ({"data_mode": "live"}, "data_mode_mismatch"),
])
def test_run_research_rejects_invalid_evidence(
    research_request, research_state, change, code,
):
    data = research_state["structured_response"].model_dump()
    data.update(change)
    research_state["structured_response"] = ResearchOutput.model_validate(data)

    class FakeAgent:
        async def astream(self, *args, **kwargs):
            yield research_state

    result = asyncio.run(run_research(FakeAgent(), research_request))

    assert set(result) == {"run_id", "status", "output", "error", "events"}
    assert result["status"] == "failed"
    assert result["output"] is None
    assert result["error"] == make_public_error(code).model_dump()
    assert result["events"][-1] == {
        "type": "run_finished",
        "run_id": result["run_id"],
        "status": "failed",
        "error": result["error"],
    }


@pytest.mark.parametrize("error, code", [
    (ModelCallLimitExceededError(3, 3, None, 3), "budget_exhausted"),
    (ToolCallLimitExceededError(5, 5, None, 4), "budget_exhausted"),
    (httpx.ReadTimeout("private model details"), "model_timeout"),
    (TimeoutError("private deadline details"), "total_timeout"),
    (RuntimeError("private runtime details"), "model_error"),
])
def test_run_research_runtime_failure_preserves_events(
    research_request, research_state, error, code,
):
    class FakeAgent:
        async def astream(self, *args, **kwargs):
            yield research_state
            raise error

    result = asyncio.run(run_research(FakeAgent(), research_request))

    assert set(result) == {"run_id", "status", "output", "error", "events"}
    assert result["status"] == "failed"
    assert result["output"] is None
    assert result["error"] == make_public_error(code).model_dump()
    assert [event["type"] for event in result["events"]] == [
        "run_started", "tool_requested", "tool_succeeded", "run_finished",
    ]
    assert result["events"][-1]["error"] == result["error"]


def test_run_research_deadline_cancels_stream(monkeypatch, research_request):
    cancelled = []

    class SlowAgent:
        async def astream(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
                yield
            finally:
                cancelled.append(True)

    monkeypatch.setattr(langchain_agent, "TASK_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(run_research(SlowAgent(), research_request))

    assert result["status"] == "failed"
    assert result["output"] is None
    assert result["error"] == make_public_error("total_timeout").model_dump()
    assert [event["type"] for event in result["events"]] == [
        "run_started", "run_finished",
    ]
    assert cancelled == [True]


def test_run_research_maps_structured_output_failure(research_request):
    model = ToolCallingFakeModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "ResearchOutput",
        "args": {"status": "completed"},
        "id": "call-output",
    }])])
    agent = build_langchain_agent(
        model,
        response_format=ToolStrategy(ResearchOutput, handle_errors=False),
    )

    result = asyncio.run(run_research(agent, research_request))

    assert result["status"] == "failed"
    assert result["output"] is None
    assert result["error"] == make_public_error("invalid_output").model_dump()
    assert result["events"][-1]["status"] == "failed"


@pytest.mark.parametrize("budget", ["model", "tool"])
def test_run_research_enforces_real_budget(research_request, budget):
    calls_per_round = [1, 1, 1, 1] if budget == "model" else [1, 4]
    model = ToolCallingFakeModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "get_quote",
            "args": {"company_id": "NVDA"},
            "id": f"call-{round_number}-{call_number}",
        } for call_number in range(count)])
        for round_number, count in enumerate(calls_per_round)
    ])

    result = asyncio.run(run_research(build_langchain_agent(model), research_request))

    assert result["status"] == "failed"
    assert result["output"] is None
    assert result["error"] == make_public_error("budget_exhausted").model_dump()
    completed_tools = [
        event for event in result["events"] if event["type"] == "tool_succeeded"
    ]
    assert len(completed_tools) == (3 if budget == "model" else 1)
