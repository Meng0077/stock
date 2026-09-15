"""D07 Step 8：最小 LangChain Agent 的离线契约与工具轨迹测试。"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from pydantic import Field

from stock_agent.agents import langchain_agent, langchain_tools
from stock_agent.agents.langchain_agent import (
    SYSTEM_PROMPT,
    build_agent_input,
    build_langchain_agent,
    invoke_langchain_agent,
)
from stock_agent.agents.langchain_tools import build_langchain_tools
from stock_agent.schemas.research import ResearchRequest


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


@pytest.mark.parametrize("selected_names", [[], ["get_quote"], ["get_company_profile"]])
def test_build_agent_accepts_canonical_tool_subsets_and_system_prompt(
    monkeypatch,
    selected_names,
):
    allowed = {
        tool.name: tool for tool in build_langchain_tools()
    }
    selected = [allowed[name] for name in selected_names]
    captured = {}
    sentinel = object()

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(langchain_agent, "create_agent", fake_create_agent)

    assert build_langchain_agent("offline-model", selected) is sentinel
    assert captured == {
        "model": "offline-model",
        "tools": selected,
        "system_prompt": SYSTEM_PROMPT,
    }


@pytest.mark.parametrize("case", ["duplicate", "unknown", "impersonated"])
def test_build_agent_rejects_tools_outside_canonical_subset(case):
    allowed = build_langchain_tools()
    invalid_tools = {
        "duplicate": [allowed[0], allowed[0]],
        "unknown": [SimpleNamespace(name="delete_file")],
        "impersonated": [SimpleNamespace(name=allowed[0].name)],
    }[case]

    with pytest.raises(ValueError, match="unique subset"):
        build_langchain_agent("offline-model", invalid_tools)


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
    quote_tool = next(
        tool for tool in build_langchain_tools() if tool.name == "get_quote"
    )
    agent = build_langchain_agent(model, [quote_tool])

    state = asyncio.run(invoke_langchain_agent(agent, research_request))
    messages = state["messages"]

    assert model.bound_tool_names == ["get_quote"]
    assert [type(message) for message in messages] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert messages[1].tool_calls[0]["name"] == "get_quote"
    assert messages[2].name == "get_quote"
    assert messages[2].tool_call_id == "call-1"
    assert json.loads(messages[2].content) == {
        "company_id": "NVDA",
        "price": 100.0,
        "currency": "USD",
        "quoted_at": "2026-09-11T09:00:00+08:00",
        "data_mode": "fixture",
        "source": "本地教学模拟数据",
        "note": "固定虚构报价，仅用于验证工具调用；报价时间也是预设的教学时间。",
    }
    assert messages[3].tool_calls == []


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
    quote_tool = next(
        tool for tool in build_langchain_tools() if tool.name == "get_quote"
    )
    agent = build_langchain_agent(model, [quote_tool])

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
