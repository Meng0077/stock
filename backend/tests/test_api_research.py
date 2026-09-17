"""D10：自然语言研究 API、生产依赖配置和 CLI 的离线验收。

保留真实 FastAPI、LangChain loop、registry 和证据校验，只替换模型响应。
不读取 .env，不创建真实模型客户端，不访问网络，不包含前端测试。
"""

import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from stock_agent.agents.langchain import langchain_tools
from stock_agent.api import dependencies
from stock_agent.api.app import create_app
from stock_agent.api.research import build_research_request
from stock_agent.schemas.errors import make_public_error
from stock_agent.schemas.research import ResearchInput
from stock_agent.schemas.research_output import ResearchOutput


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_UUID = UUID("00000000-0000-0000-0000-000000000001")
EVIDENCE_ID = f"E-{EVIDENCE_UUID.hex}"


class OfflineToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def tool_message(name, arguments, call_id):
    return AIMessage(content="", tool_calls=[{
        "name": name, "args": arguments, "id": call_id,
    }])


def quote_output():
    return {
        "status": "completed",
        "facts": [{
            "text": "NVDA 教学模拟报价为 100 USD，不是实时行情。",
            "evidence_ids": [EVIDENCE_ID],
        }],
        "inferences": [],
        "missing_information": [],
        "data_mode": "fixture",
    }


@pytest.fixture(autouse=True)
def clear_agent_cache():
    dependencies.get_langchain_agent.cache_clear()
    yield
    dependencies.get_langchain_agent.cache_clear()


@pytest.fixture
def offline_config(monkeypatch):
    config = SimpleNamespace(model="offline-model", api_key="offline-secret-key")
    monkeypatch.setattr(dependencies, "get_llm_config", lambda path: config)
    return config


def client_for(agent):
    application = create_app()
    application.dependency_overrides[dependencies.get_langchain_agent] = lambda: agent
    return TestClient(application)


def test_production_dependency_configures_structured_output_and_non_thinking(
    monkeypatch, offline_config,
):
    captured = {}
    model = object()
    agent = object()

    def fake_model(**kwargs):
        captured["model_options"] = kwargs
        return model

    def fake_builder(**kwargs):
        captured["agent_options"] = kwargs
        return agent

    monkeypatch.setattr(dependencies, "ChatDeepSeek", fake_model)
    monkeypatch.setattr(dependencies, "build_langchain_agent", fake_builder)

    assert dependencies.get_langchain_agent() is agent
    assert dependencies.get_langchain_agent() is agent
    assert dependencies.get_langchain_agent.cache_info().misses == 1
    assert captured["model_options"] == {
        "model": offline_config.model,
        "api_key": offline_config.api_key,
        "temperature": 0,
        "timeout": dependencies.MODEL_TIMEOUT_SECONDS,
        "max_retries": 0,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    assert captured["agent_options"]["model"] is model
    strategy = captured["agent_options"]["response_format"]
    assert isinstance(strategy, ToolStrategy)
    assert strategy.schema is ResearchOutput


def test_natural_language_is_normalized_on_server():
    before = datetime.now(timezone.utc)
    request = build_research_request(ResearchInput(message="查询 NVDA 教学报价"))
    after = datetime.now(timezone.utc)

    assert request.company_id == "NVDA"
    assert request.question == "查询 NVDA 教学报价"
    assert request.data_mode == "fixture"
    assert before <= request.as_of <= after
    assert request.as_of.utcoffset().total_seconds() == 0


def test_research_api_runs_real_tool_and_returns_public_result(
    monkeypatch, offline_config,
):
    monkeypatch.setattr(langchain_tools, "uuid4", lambda: EVIDENCE_UUID)
    model = OfflineToolModel(responses=[
        tool_message("get_quote", {"company_id": "NVDA"}, "call-quote"),
        tool_message("ResearchOutput", quote_output(), "call-output"),
    ])
    monkeypatch.setattr(dependencies, "ChatDeepSeek", lambda **kwargs: model)

    # 不替换 Agent 依赖：让生产依赖真实创建配置了 ToolStrategy 的 graph。
    with TestClient(create_app()) as client:
        response = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"run_id", "status", "result", "error"}
    UUID(body["run_id"])
    assert body["status"] == "completed"
    assert body["result"] == quote_output()
    assert body["error"] is None
    assert "output" not in body
    assert "events" not in body
    assert offline_config.api_key not in response.text


def test_repeated_requests_to_cached_agent_have_distinct_run_ids(
    monkeypatch, offline_config,
):
    monkeypatch.setattr(langchain_tools, "uuid4", lambda: EVIDENCE_UUID)
    model = OfflineToolModel(responses=[
        tool_message("get_quote", {"company_id": "NVDA"}, "call-quote"),
        tool_message("ResearchOutput", quote_output(), "call-output"),
    ])
    monkeypatch.setattr(dependencies, "ChatDeepSeek", lambda **kwargs: model)

    with TestClient(create_app()) as client:
        first = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})
        second = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "completed"
    assert UUID(first.json()["run_id"]) != UUID(second.json()["run_id"])
    assert dependencies.get_langchain_agent.cache_info().misses == 1


def test_unsupported_company_returns_insufficient_information():
    output = {
        "status": "insufficient_information",
        "facts": [],
        "inferences": [],
        "missing_information": ["当前仅支持 NVDA，缺少 TSLA 的教学模拟报价。"],
        "data_mode": "fixture",
    }
    model = OfflineToolModel(responses=[
        tool_message("get_quote", {"company_id": "TSLA"}, "call-tsla"),
        tool_message("ResearchOutput", output, "call-output"),
    ])
    agent = dependencies.build_langchain_agent(model, response_format=ToolStrategy(ResearchOutput))

    with client_for(agent) as client:
        response = client.post("/api/research", json={"message": "查询 TSLA 教学报价"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_information"
    assert body["result"] == output
    assert body["error"] is None


@pytest.mark.parametrize("payload", [
    {},
    {"message": ""},
    {"message": "x" * 2001},
    {"message": 123},
    {"message": "查询 NVDA", "company_id": "TSLA"},
])
def test_invalid_request_returns_422_without_invoking_agent(payload):
    with client_for(object()) as client:
        response = client.post("/api/research", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "body"


@pytest.mark.parametrize("message", ["查询教学报价", "   "])
def test_missing_company_returns_400_without_invoking_agent(message):
    with client_for(object()) as client:
        response = client.post("/api/research", json={"message": message})

    assert response.status_code == 400
    assert response.json() == {"detail": "没有识别到股票代码"}


@pytest.mark.parametrize("error,code", [
    (ModelCallLimitExceededError(3, 3, None, 3), "budget_exhausted"),
    (ToolCallLimitExceededError(5, 5, None, 4), "budget_exhausted"),
    (httpx.ReadTimeout("private provider details"), "model_timeout"),
    (TimeoutError("private deadline details"), "total_timeout"),
    (RuntimeError("PRIVATE_API_KEY Authorization traceback"), "model_error"),
])
def test_runtime_failure_returns_only_safe_public_fields(error, code):
    class FailingAgent:
        async def astream(self, state, **kwargs):
            yield state
            raise error

    with client_for(FailingAgent()) as client:
        response = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})

    assert response.status_code == 200
    body = response.json()
    UUID(body["run_id"])
    assert body == {
        "run_id": body["run_id"],
        "status": "failed",
        "result": None,
        "error": make_public_error(code).model_dump(),
    }
    assert "private" not in response.text.casefold()
    assert "authorization" not in response.text.casefold()
    assert "traceback" not in response.text.casefold()


@pytest.mark.parametrize("data_mode,code", [
    ("fixture", "invalid_evidence"),
    ("live", "data_mode_mismatch"),
])
def test_api_does_not_publish_output_that_fails_evidence_validation(data_mode, code):
    output = quote_output()
    output["data_mode"] = data_mode

    class UnverifiedAgent:
        async def astream(self, state, **kwargs):
            yield {"messages": [], "structured_response": ResearchOutput.model_validate(output)}

    with client_for(UnverifiedAgent()) as client:
        response = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"] == make_public_error(code).model_dump()


def test_structured_verification_cli_can_run_offline(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "verify_langchain_structured", ROOT / "evals" / "verify_langchain_structured.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    output = {
        "status": "insufficient_information", "facts": [], "inferences": [],
        "missing_information": ["缺少 TSLA 的教学模拟报价。"], "data_mode": "fixture",
    }
    model = OfflineToolModel(responses=[
        tool_message("get_quote", {"company_id": "TSLA"}, "call-tsla"),
        tool_message("ResearchOutput", output, "call-output"),
    ])
    monkeypatch.setattr(cli, "get_llm_config", lambda path: SimpleNamespace(
        model="offline-model", api_key="offline-secret-key",
    ))
    monkeypatch.setattr(cli, "ChatDeepSeek", lambda **kwargs: model)

    asyncio.run(cli.main())

    printed = capsys.readouterr().out
    assert "insufficient_information" in printed
    assert "run_finished" in printed
    assert "offline-secret-key" not in printed
