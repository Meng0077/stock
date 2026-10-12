"""自然语言研究 API、生产依赖配置和 CLI 的离线验收。

保留真实 FastAPI 路由和 LangGraph Workflow 边界，只替换 Graph 运行时。
原有 LangChain 生产依赖和 CLI 仍保留离线验收。
不读取 .env，不创建真实模型客户端，不访问网络，不包含前端测试。
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from stock_agent.api import dependencies
from stock_agent.api.app import create_app
from stock_agent.api.research import build_research_request
from stock_agent.schemas.errors import make_public_error
from stock_agent.schemas.research import ResearchInput
from stock_agent.schemas.research_output import ResearchOutput
from stock_agent.market.schemas import Quote
from stock_agent.schemas.research import ResearchRequest


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
            "text": "NVDA 长桥报价为 100 USD。",
            "evidence_ids": [EVIDENCE_ID],
        }],
        "inferences": [],
        "missing_information": [],
        "data_mode": "live",
    }


@pytest.fixture(autouse=True)
def clear_agent_cache(monkeypatch):
    provider = Mock()
    provider.get_quote.side_effect = lambda symbol, *, as_of: Quote(
        symbol=symbol,
        price=Decimal("100"),
        currency="USD",
        quoted_at=as_of - timedelta(seconds=30),
        received_at=as_of - timedelta(seconds=29),
        session="regular",
        data_mode="live",
        is_delayed=None,
        source="longbridge",
    )
    monkeypatch.setattr(
        dependencies,
        "build_longbridge_market_provider",
        Mock(return_value=provider),
    )

    dependencies.get_chat_model.cache_clear()
    dependencies.get_langchain_agent.cache_clear()
    dependencies.get_research_graph.cache_clear()
    dependencies.get_macro_snapshot_builder.cache_clear()
    dependencies.get_market_data_provider.cache_clear()
    yield
    dependencies.get_chat_model.cache_clear()
    dependencies.get_langchain_agent.cache_clear()
    dependencies.get_research_graph.cache_clear()
    dependencies.get_macro_snapshot_builder.cache_clear()
    dependencies.get_market_data_provider.cache_clear()


@pytest.fixture
def offline_config(monkeypatch):
    config = SimpleNamespace(model="offline-model", api_key="offline-secret-key")
    monkeypatch.setattr(dependencies, "get_llm_config", lambda path: config)
    return config


class FakeResearchGraph:
    def __init__(
        self,
        *,
        result=None,
        error=None,
        state_values=None,
        state_next=(),
        state_interrupts=(),
    ):
        self.result = result or {"output": "研究完成"}
        self.error = error
        self.state_values = state_values or {}
        self.state_next = state_next
        self.state_interrupts = state_interrupts
        self.calls = []
        self.completed_threads = set()

    async def astream(self, graph_input, **kwargs):
        self.calls.append((graph_input, kwargs))
        if self.error is not None:
            raise self.error
        thread_id = kwargs["config"]["configurable"]["thread_id"]
        self.completed_threads.add(thread_id)
        if False:
            yield None

    async def aget_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        if thread_id in self.completed_threads:
            interrupts = tuple(self.result.get("__interrupt__", ()))
            values = {
                **self.state_values,
                **{
                    key: value
                    for key, value in self.result.items()
                    if key != "__interrupt__"
                },
            }
            return SimpleNamespace(
                values=values,
                next=(),
                interrupts=interrupts,
            )
        return SimpleNamespace(
            values=self.state_values,
            next=self.state_next,
            interrupts=self.state_interrupts,
        )


def client_for(graph):
    application = create_app()
    application.dependency_overrides[dependencies.get_research_graph] = lambda: graph
    return TestClient(application)


def test_macro_builder_dependency_is_lazy_and_cached(monkeypatch):
    builder = object()
    create_builder = Mock(return_value=builder)
    monkeypatch.setattr(
        dependencies,
        "build_macro_snapshot_builder",
        create_builder,
    )

    factory = dependencies.get_macro_builder_factory()

    create_builder.assert_not_called()
    assert factory() is builder
    assert factory() is builder
    create_builder.assert_called_once_with()


def test_market_provider_dependency_is_lazy_and_cached(monkeypatch):
    provider = object()
    create_provider = Mock(return_value=provider)
    monkeypatch.setattr(
        dependencies,
        "build_longbridge_market_provider",
        create_provider,
    )

    factory = dependencies.get_market_provider_factory()

    create_provider.assert_not_called()
    assert factory() is provider
    assert factory() is provider
    create_provider.assert_called_once_with()


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


@pytest.mark.parametrize("message", [
    "查询 NVDA 教学报价",
    "NVDA今日行情如何",
    "nvda今日行情如何",
])
def test_natural_language_is_normalized_on_server(message):
    before = datetime.now(timezone.utc)
    request = build_research_request(
        ResearchInput(message=message),
    )
    after = datetime.now(timezone.utc)

    assert request.company_ids == []
    assert request.question == message
    assert request.data_mode == "mixed"
    assert before <= request.as_of <= after
    offset = request.as_of.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


@pytest.mark.parametrize("message", [
    "查询 NVDA 教学报价",
    "NVDA今日行情如何",
    "nvda今日行情如何",
])
def test_research_api_starts_workflow_and_returns_public_result(message):
    graph = FakeResearchGraph(result={"output": "NVDA 报价研究完成"})

    # 不替换路由实现；只用离线 Graph 隔离模型和 Provider。
    with client_for(graph) as client:
        response = client.post("/api/research", json={"message": message})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "thread_id",
        "status",
        "result",
        "clarification",
        "error",
    }
    UUID(body["thread_id"])
    assert body["status"] == "completed"
    assert body["result"] == "NVDA 报价研究完成"
    assert body["clarification"] is None
    assert body["error"] is None
    initial_state, kwargs = graph.calls[0]
    assert initial_state["request"].company_ids == []
    assert initial_state["request"].question == message
    assert kwargs["config"]["configurable"]["thread_id"] == body["thread_id"]


def test_repeated_requests_use_distinct_workflow_thread_ids():
    graph = FakeResearchGraph()

    with client_for(graph) as client:
        first = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})
        second = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "completed"
    assert UUID(first.json()["thread_id"]) != UUID(second.json()["thread_id"])
    assert len(graph.calls) == 2


def test_research_api_uses_client_supplied_thread_id():
    graph = FakeResearchGraph(result={"output": "研究完成"})
    thread_id = "00000000-0000-0000-0000-000000000038"

    with client_for(graph) as client:
        response = client.post(
            "/api/research",
            json={
                "message": "查询 NVDA 教学报价",
                "thread_id": thread_id,
            },
        )

    assert response.status_code == 200
    assert response.json()["thread_id"] == thread_id
    assert graph.calls[0][1]["config"] == {
        "configurable": {"thread_id": thread_id}
    }


def test_research_api_rejects_existing_thread_id():
    thread_id = "00000000-0000-0000-0000-000000000038"
    graph = FakeResearchGraph(state_values={"request": object()})

    with client_for(graph) as client:
        response = client.post(
            "/api/research",
            json={
                "message": "查询 NVDA 教学报价",
                "thread_id": thread_id,
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"Research workflow {thread_id} already exists"
    }
    assert graph.calls == []


def test_research_api_returns_target_clarification_interrupt():
    clarification = {
        "type": "target_clarification",
        "message": "请选择一个 ticker。",
        "candidates": ["GOOG", "GOOGL"],
    }
    graph = FakeResearchGraph(
        result={
            "__interrupt__": [SimpleNamespace(value=clarification)],
        }
    )

    with client_for(graph) as client:
        response = client.post("/api/research", json={"message": "Google 怎么看"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_input"
    assert body["clarification"] == clarification
    assert body["result"] is None
    assert body["error"] is None


@pytest.mark.parametrize("payload", [
    {},
    {"message": ""},
    {"message": "x" * 2001},
    {"message": 123},
    {"message": "查询 NVDA", "company_id": "TSLA"},
])
def test_invalid_request_returns_422_without_invoking_graph(payload):
    graph = FakeResearchGraph()
    with client_for(graph) as client:
        response = client.post("/api/research", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "body"
    assert graph.calls == []


def test_request_without_security_target_keeps_company_ids_empty():
    request = build_research_request(
        ResearchInput(message="最新 CPI 是多少"),
    )

    assert request.company_ids == []


@pytest.mark.parametrize("error,code", [
    (ModelCallLimitExceededError(3, 3, None, 3), "budget_exhausted"),
    (ToolCallLimitExceededError(5, 5, None, 4), "budget_exhausted"),
    (httpx.ReadTimeout("private provider details"), "model_timeout"),
    (TimeoutError("private deadline details"), "total_timeout"),
    (RuntimeError("PRIVATE_API_KEY Authorization traceback"), "model_error"),
])
def test_runtime_failure_returns_only_safe_public_fields(error, code):
    graph = FakeResearchGraph(error=error)
    with client_for(graph) as client:
        response = client.post("/api/research", json={"message": "查询 NVDA 教学报价"})

    assert response.status_code == 200
    body = response.json()
    UUID(body["thread_id"])
    assert body == {
        "thread_id": body["thread_id"],
        "status": "failed",
        "result": None,
        "clarification": None,
        "error": make_public_error(code).model_dump(),
    }
    assert "private" not in response.text.casefold()
    assert "authorization" not in response.text.casefold()
    assert "traceback" not in response.text.casefold()


def test_resume_returns_404_for_unknown_workflow():
    graph = FakeResearchGraph(state_values={})
    with client_for(graph) as client:
        response = client.post(
            "/api/research/resume",
            json={"thread_id": "missing", "answer": "NVDA"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Research workflow does not exist"}
    assert graph.calls == []


def test_resume_uses_saved_request_and_same_thread_id():
    request = ResearchRequest(
        company_ids=[],
        question="比较 NVDA 和 AAPL",
        data_mode="mixed",
        as_of=datetime(2026, 10, 10, 16, tzinfo=timezone.utc),
    )
    graph = FakeResearchGraph(
        result={"output": "NVDA 研究完成"},
        state_values={"request": request},
    )

    with client_for(graph) as client:
        response = client.post(
            "/api/research/resume",
            json={"thread_id": "thread-1", "answer": "NVDA"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
        "status": "completed",
        "result": "NVDA 研究完成",
        "clarification": None,
        "error": None,
    }
    command, kwargs = graph.calls[0]
    assert command.resume == "NVDA"
    assert kwargs["config"] == {
        "configurable": {"thread_id": "thread-1"}
    }
    assert kwargs["context"].as_of == request.as_of


def test_resume_runtime_failure_returns_safe_public_error():
    request = ResearchRequest(
        company_ids=[],
        question="Google 怎么看",
        data_mode="mixed",
        as_of=datetime(2026, 10, 10, 16, tzinfo=timezone.utc),
    )
    graph = FakeResearchGraph(
        error=RuntimeError("PRIVATE_API_KEY resume traceback"),
        state_values={"request": request},
    )

    with client_for(graph) as client:
        response = client.post(
            "/api/research/resume",
            json={"thread_id": "thread-1", "answer": "GOOGL"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
        "status": "failed",
        "result": None,
        "clarification": None,
        "error": make_public_error("model_error").model_dump(),
    }
    assert "private" not in response.text.casefold()
    assert "traceback" not in response.text.casefold()


def test_continue_returns_404_for_unknown_workflow():
    graph = FakeResearchGraph()

    with client_for(graph) as client:
        response = client.post("/api/research/missing/continue")

    assert response.status_code == 404
    assert response.json() == {"detail": "Research workflow does not exist"}
    assert graph.calls == []


def test_continue_rejects_workflow_waiting_for_user_input():
    graph = FakeResearchGraph(
        state_values={"request": object()},
        state_next=("clarify_target",),
        state_interrupts=(object(),),
    )

    with client_for(graph) as client:
        response = client.post("/api/research/thread-1/continue")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Research workflow is waiting for user input"
    }
    assert graph.calls == []


def test_continue_rejects_completed_workflow():
    graph = FakeResearchGraph(
        state_values={"request": object()},
        state_next=(),
    )

    with client_for(graph) as client:
        response = client.post("/api/research/thread-1/continue")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Research workflow has already completed"
    }
    assert graph.calls == []


def test_continue_uses_saved_request_and_same_thread_id():
    request = ResearchRequest(
        company_ids=["NVDA"],
        question="NVDA 当前走势怎么看",
        data_mode="mixed",
        as_of=datetime(2026, 10, 11, 16, tzinfo=timezone.utc),
    )
    graph = FakeResearchGraph(
        result={"output": "NVDA 研究完成"},
        state_values={"request": request},
        state_next=("research",),
    )

    with client_for(graph) as client:
        response = client.post("/api/research/thread-1/continue")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
        "status": "completed",
        "result": "NVDA 研究完成",
        "clarification": None,
        "error": None,
    }
    graph_input, kwargs = graph.calls[0]
    assert graph_input is None
    assert kwargs["config"] == {
        "configurable": {"thread_id": "thread-1"}
    }
    assert kwargs["context"].as_of == request.as_of


def test_cancel_returns_404_when_workflow_is_not_running():
    with client_for(FakeResearchGraph()) as client:
        response = client.post("/api/research/missing/cancel")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Research workflow missing is not running"
    }


def test_cancel_stops_active_api_workflow_and_returns_cancelled_status():
    async def scenario() -> None:
        class BlockingResearchGraph(FakeResearchGraph):
            def __init__(self):
                super().__init__()
                self.started = asyncio.Event()
                self.cancelled = asyncio.Event()

            async def astream(self, graph_input, **kwargs):
                self.calls.append((graph_input, kwargs))
                self.started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled.set()
                if False:
                    yield None

        graph = BlockingResearchGraph()
        application = create_app()
        application.dependency_overrides[
            dependencies.get_research_graph
        ] = lambda: graph
        thread_id = "00000000-0000-0000-0000-000000000038"
        transport = httpx.ASGITransport(app=application)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            research_task = asyncio.create_task(
                client.post(
                    "/api/research",
                    json={
                        "message": "NVDA 当前走势怎么看",
                        "thread_id": thread_id,
                    },
                )
            )
            await graph.started.wait()

            cancel_response = await client.post(
                f"/api/research/{thread_id}/cancel"
            )
            research_response = await research_task

        assert cancel_response.status_code == 200
        assert cancel_response.json() == {
            "thread_id": thread_id,
            "status": "cancelling",
        }
        assert research_response.status_code == 200
        assert research_response.json() == {
            "thread_id": thread_id,
            "status": "cancelled",
            "result": None,
            "clarification": None,
            "error": None,
        }
        assert graph.cancelled.is_set()

    asyncio.run(scenario())


def test_structured_verification_cli_can_run_offline(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "verify_langchain_structured", ROOT / "evals" / "verify_langchain_structured.py",
    )
    assert spec is not None
    assert spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    output = {
        "status": "insufficient_information", "facts": [], "inferences": [],
        "missing_information": ["缺少 NVDA 的教学模拟报价。"], "data_mode": None,
    }
    model = OfflineToolModel(responses=[
        tool_message("get_quote", {"company_id": "NVDA"}, "call-nvda"),
        tool_message("ResearchOutput", output, "call-output"),
    ])
    monkeypatch.setattr(cli, "get_llm_config", lambda path: SimpleNamespace(
        model="offline-model", api_key="offline-secret-key",
    ))
    monkeypatch.setattr(cli, "ChatDeepSeek", lambda **kwargs: model)
    provider = Mock()
    provider.get_quote.return_value = None
    monkeypatch.setattr(
        cli,
        "build_longbridge_market_provider",
        Mock(return_value=provider),
    )

    asyncio.run(cli.main())

    printed = capsys.readouterr().out
    assert "insufficient_information" in printed
    assert "run_finished" in printed
    assert "offline-secret-key" not in printed
