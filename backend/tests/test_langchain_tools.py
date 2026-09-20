"""D07 Step 5：离线验证 LangChain Tool adapter 与现有 registry 的边界。"""

import asyncio
from datetime import datetime, timezone
import json

import pytest
from langchain.tools import ToolRuntime
from pydantic import ValidationError

from stock_agent.agents.langchain import langchain_tools
from stock_agent.agents.context import ResearchContext
from stock_agent.schemas.tool_params import CompanyToolParams, KnowledgeToolParams
from stock_agent.tools.registry import TOOL_REGISTRY, execute_tool


TOOL_NAMES = ("get_quote", "get_company_profile")


def tools_by_name():
    """返回以 LangChain 工具名为键的本次白名单，方便各测试复用。"""
    return {tool.name: tool for tool in langchain_tools.build_langchain_tools()}


def test_build_langchain_tools_returns_exact_allowlist():
    tools = langchain_tools.build_langchain_tools()

    assert [tool.name for tool in tools] == [*TOOL_NAMES, "retrieve_knowledge"]
    assert len({tool.name for tool in tools}) == len(TOOL_NAMES) + 1


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_adapter_reuses_company_tool_params_schema(tool_name):
    tool = tools_by_name()[tool_name]

    assert tool.args_schema is CompanyToolParams
    assert tool.args_schema.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
    "payload,field,error_type",
    [
        ({"company_id": ""}, "company_id", "string_too_short"),
        ({"company_id": "NVDA", "extra": 1}, "extra", "extra_forbidden"),
    ],
)
@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_invalid_arguments_are_rejected_before_handler(
    monkeypatch,
    tool_name,
    payload,
    field,
    error_type,
):
    def unexpected_handler(company_id):
        raise AssertionError(f"非法参数不应执行 handler：{company_id}")

    monkeypatch.setitem(TOOL_REGISTRY[tool_name], "handler", unexpected_handler)

    with pytest.raises(ValidationError) as caught:
        asyncio.run(tools_by_name()[tool_name].ainvoke(payload))

    errors = caught.value.errors(include_input=False)
    assert any(
        error["loc"] == (field,) and error["type"] == error_type
        for error in errors
    )


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
@pytest.mark.parametrize("company_id", ["NVDA", "  NVDA  "])
def test_adapter_result_matches_execute_tool(tool_name, company_id):
    payload = {"company_id": company_id}

    async def invoke_both():
        adapter_result = await tools_by_name()[tool_name].ainvoke(payload)
        registry_result = await execute_tool(tool_name, payload)
        return adapter_result, registry_result

    adapter_result, registry_result = asyncio.run(invoke_both())

    evidence_id = adapter_result.pop("evidence_id")
    assert evidence_id.startswith("E-")
    assert adapter_result == registry_result
    assert adapter_result["company_id"] == "NVDA"
    assert adapter_result["data_mode"] == "fixture"


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_adapter_only_delegates_to_execute_tool(monkeypatch, tool_name):
    calls = []

    async def fake_execute_tool(actual_name, arguments):
        calls.append((actual_name, arguments))
        return {"delegated": True}

    monkeypatch.setattr(langchain_tools, "execute_tool", fake_execute_tool)

    result = asyncio.run(
        tools_by_name()[tool_name].ainvoke({"company_id": "  NVDA  "})
    )

    assert result.pop("evidence_id").startswith("E-")
    assert result == {"delegated": True}
    assert calls == [(tool_name, {"company_id": "NVDA"})]


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_unsupported_company_is_rejected_by_existing_handler(tool_name):
    assert CompanyToolParams.model_validate(
        {"company_id": "AAPL"}
    ).company_id == "AAPL"

    with pytest.raises(ValueError, match="不支持的公司标识"):
        asyncio.run(tools_by_name()[tool_name].ainvoke({"company_id": "AAPL"}))


def test_unknown_tool_has_no_langchain_or_registry_execution_path():
    assert "delete_file" not in tools_by_name()

    with pytest.raises(ValueError, match="未知工具"):
        asyncio.run(execute_tool("delete_file", {"company_id": "NVDA"}))


def test_knowledge_adapter_uses_runtime_as_of(monkeypatch):
    calls = []
    documents = [{"evidence_id": "rag:NVDA:nvda.txt:2", "content": "AI infrastructure demand"}]

    def fake_retrieve_knowledge(company_id, question, as_of, *, engine, config):
        calls.append((company_id, question, as_of, engine, config))
        return documents

    monkeypatch.setattr(langchain_tools, "retrieve_knowledge", fake_retrieve_knowledge)
    tool = tools_by_name()["retrieve_knowledge"]
    assert issubclass(tool.args_schema, KnowledgeToolParams)
    assert set(tool.tool_call_schema.model_json_schema()["properties"]) == {
        "company_id",
        "question",
    }
    as_of = datetime(2026, 9, 17, tzinfo=timezone.utc)
    engine = object()
    index_config = ResearchContext(as_of=as_of).index_config
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            engine=engine,
            index_config=index_config,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-rag",
        store=None,
    )
    result = asyncio.run(tool.coroutine(
        company_id="NVDA",
        question="What drives data center revenue?",
        runtime=runtime,
    ))
    assert calls == [(
        "NVDA",
        "What drives data center revenue?",
        as_of,
        engine,
        index_config,
    )]
    assert json.loads(result) == documents
