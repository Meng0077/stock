"""D07 Step 5：离线验证 LangChain Tool adapter 与现有 registry 的边界。"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from unittest.mock import Mock

import pytest
from langchain.tools import ToolRuntime
from pydantic import ValidationError

from stock_agent.agents.langchain import langchain_tools
from stock_agent.agents.context import ResearchContext
from stock_agent.financial.schemas import FinancialFact
from stock_agent.macro.models.metric import MacroMetricSnapshot
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.models.snapshot import MacroSnapshot
from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.schemas import Bar, Quote
from stock_agent.schemas.tool_params import CompanyToolParams, KnowledgeToolParams
from stock_agent.tools.registry import TOOL_REGISTRY, execute_tool


TOOL_NAMES = ("get_quote", "get_company_profile")


def make_completed_bars(
    *,
    as_of: datetime,
    count: int = 60,
) -> list[Bar]:
    start = as_of - timedelta(days=count + 1)
    return [
        Bar(
            symbol="NVDA",
            timeframe="1d",
            start_at=start + timedelta(days=index),
            end_at=start + timedelta(days=index, hours=6),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=1_000_000 + index,
            is_complete=True,
            adjustment="forward_adjusted",
            updated_at=start + timedelta(days=index, hours=6),
            received_at=start + timedelta(days=index, hours=6),
            source="fixture",
            data_mode="historical",
        )
        for index in range(count)
    ]


def tools_by_name():
    """返回以 LangChain 工具名为键的本次白名单，方便各测试复用。"""
    return {tool.name: tool for tool in langchain_tools.build_langchain_tools()}


def test_build_langchain_tools_returns_exact_allowlist():
    tools = langchain_tools.build_langchain_tools()

    assert [tool.name for tool in tools] == [
        *TOOL_NAMES,
        "retrieve_knowledge",
        "get_financial_facts",
        "get_macro_snapshot",
        "get_technical_analysis",
    ]
    assert len({tool.name for tool in tools}) == len(TOOL_NAMES) + 4


def test_company_profile_adapter_reuses_company_tool_params_schema():
    tool = tools_by_name()["get_company_profile"]

    assert tool.args_schema is CompanyToolParams
    assert tool.args_schema.model_json_schema()["additionalProperties"] is False


def test_quote_adapter_exposes_only_company_id_to_model():
    tool = tools_by_name()["get_quote"]

    assert issubclass(tool.args_schema, CompanyToolParams)
    assert set(tool.tool_call_schema.model_json_schema()["properties"]) == {
        "company_id"
    }


@pytest.mark.parametrize(
    "payload,field,error_type",
    [
        ({"company_id": ""}, "company_id", "string_too_short"),
        ({"company_id": "NVDA", "extra": 1}, "extra", "extra_forbidden"),
    ],
)
@pytest.mark.parametrize("tool_name", ["get_company_profile"])
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


@pytest.mark.parametrize("tool_name", ["get_company_profile"])
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


@pytest.mark.parametrize("tool_name", ["get_company_profile"])
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


@pytest.mark.parametrize("tool_name", ["get_company_profile"])
def test_unsupported_company_is_rejected_by_existing_handler(tool_name):
    assert CompanyToolParams.model_validate(
        {"company_id": "AAPL"}
    ).company_id == "AAPL"

    with pytest.raises(ValueError, match="不支持的公司标识"):
        asyncio.run(tools_by_name()[tool_name].ainvoke({"company_id": "AAPL"}))


def test_quote_adapter_uses_runtime_market_provider():
    as_of = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    quote = Quote(
        symbol="NVDA",
        price=Decimal("187.25"),
        currency="USD",
        quoted_at=datetime(2026, 9, 27, 11, 59, 30, tzinfo=timezone.utc),
        received_at=datetime(2026, 9, 27, 11, 59, 31, tzinfo=timezone.utc),
        session="post",
        data_mode="live",
        is_delayed=None,
        source="longbridge",
    )
    provider = Mock()
    provider.get_quote.return_value = quote
    factory = Mock(return_value=provider)
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            market_provider_factory=factory,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-quote",
        store=None,
    )

    result = asyncio.run(
        tools_by_name()["get_quote"].coroutine(
            company_id="NVDA",
            runtime=runtime,
        )
    )

    factory.assert_called_once_with()
    provider.get_quote.assert_called_once_with("NVDA", as_of=as_of)
    assert result["symbol"] == "NVDA"
    assert result["quote"]["price"] == "187.25"
    assert result["data_mode"] == "live"
    assert result["quote"]["source"] == "longbridge"
    assert result["quality"]["overall_status"] == "degraded"
    assert result["quality"]["results"][0]["issues"][0]["code"] == (
        "market_state_unknown"
    )
    assert result["evidence_id"].startswith("E-")


def test_quote_adapter_does_not_create_evidence_for_stale_quote():
    as_of = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    quote = Quote(
        symbol="NVDA",
        price=Decimal("187.25"),
        currency="USD",
        quoted_at=as_of - timedelta(seconds=61),
        received_at=as_of - timedelta(seconds=60),
        session="post",
        data_mode="live",
        is_delayed=False,
        source="longbridge",
    )
    provider = Mock()
    provider.get_quote.return_value = quote
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            market_provider_factory=lambda: provider,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-stale-quote",
        store=None,
    )

    result = asyncio.run(
        tools_by_name()["get_quote"].coroutine(
            company_id="NVDA",
            runtime=runtime,
        )
    )

    assert result["quote"] is None
    assert "evidence_id" not in result
    assert result["quality"]["overall_status"] == "rejected"
    assert result["quality"]["results"][0]["issues"][0]["code"] == (
        "quote_stale"
    )


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


def test_financial_adapter_uses_runtime_context(monkeypatch):
    fact = FinancialFact(
        fact_id="financial:test",
        company_id="NVDA",
        concept="NetIncomeLoss",
        value=Decimal("18775000000"),
        unit="USD",
        start_date=date(2026, 1, 26),
        end_date=date(2026, 4, 26),
        filed_date=date(2026, 5, 28),
        form="10-Q",
        accession_number="0001045810-26-000001",
        fiscal_year=2027,
        fiscal_period="Q1",
        frame="CY2026Q1",
    )
    get_facts = Mock(return_value=[fact])
    monkeypatch.setattr(langchain_tools, "get_financial_facts", get_facts)

    as_of = datetime(2026, 9, 17, tzinfo=timezone.utc)
    engine = object()
    sec_client = object()
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            engine=engine,
            sec_client=sec_client,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-financial",
        store=None,
    )

    tool = tools_by_name()["get_financial_facts"]
    assert set(tool.tool_call_schema.model_json_schema()["properties"]) == {
        "company_id",
        "concept",
        "unit",
        "period_type",
    }
    result = tool.func(
        company_id="NVDA",
        concept="NetIncomeLoss",
        unit="USD",
        period_type="quarterly",
        runtime=runtime,
    )

    get_facts.assert_called_once_with(
        engine=engine,
        client=sec_client,
        company_id="NVDA",
        concept="NetIncomeLoss",
        unit="USD",
        as_of=date(2026, 9, 17),
        period_type="quarterly",
    )
    assert result["data_mode"] == "historical"
    assert result["facts"][0]["evidence_id"] == "financial:test"


def test_macro_tool_uses_runtime_builder_and_returns_event_evidence():
    as_of = datetime(2026, 9, 20, 16, tzinfo=timezone.utc)
    release = MacroReleaseEvent(
        release_id="cpi:2026-09-11",
        release_type="cpi",
        release_date=date(2026, 9, 11),
        release_date_source="longbridge",
        period_binding="latest_assumed",
        metrics=[
            MacroMetricSnapshot(
                indicator="cpi",
                measure="mom",
                unit="percent",
                period=date(2026, 8, 1),
                actual=Decimal("0.4"),
                consensus=Decimal("0.3"),
                estimated_surprise=Decimal("0.1"),
                release_date=date(2026, 9, 11),
                source="longbridge",
            )
        ],
    )
    snapshot = MacroSnapshot(
        as_of=as_of,
        recent_releases=[release],
        fed_policy=None,
        fed_projections=[],
        treasury=None,
        warnings=[],
    )
    builder = Mock()
    builder.build_latest.return_value = snapshot
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            macro_builder_factory=lambda: builder,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-macro",
        store=None,
    )

    tool = tools_by_name()["get_macro_snapshot"]
    assert set(tool.tool_call_schema.model_json_schema()["properties"]) == {
        "release_type"
    }
    result = tool.func(release_type="cpi", runtime=runtime)

    builder.build_latest.assert_called_once_with(as_of=as_of)
    assert result["evidence_id"] == "macro:cpi:2026-09-11"
    assert result["data_mode"] == "historical"
    assert result["release"]["metrics"][0]["estimated_surprise"] == "0.1"


def test_macro_full_snapshot_filters_rejected_future_release():
    as_of = datetime(2026, 9, 20, 16, tzinfo=timezone.utc)

    def make_release(
        *,
        release_type: str,
        release_date: date,
        released_at: datetime,
    ) -> MacroReleaseEvent:
        return MacroReleaseEvent(
            release_id=f"{release_type}:{release_date.isoformat()}",
            release_type=release_type,
            release_date=release_date,
            released_at=released_at,
            release_date_source="fixture",
            period_binding="verified",
            metrics=[
                MacroMetricSnapshot(
                    indicator=("cpi" if release_type == "cpi" else "ppi"),
                    measure="mom",
                    unit="percent",
                    period=date(2026, 8, 1),
                    actual=Decimal("0.3"),
                    release_date=release_date,
                    released_at=released_at,
                    source="fixture",
                    actual_pit_status="verified",
                )
            ],
        )

    available = make_release(
        release_type="cpi",
        release_date=date(2026, 9, 11),
        released_at=datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc),
    )
    future = make_release(
        release_type="ppi",
        release_date=date(2026, 9, 21),
        released_at=datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc),
    )
    builder = Mock()
    builder.build_latest.return_value = MacroSnapshot(
        as_of=as_of,
        recent_releases=[available, future],
        fed_policy=None,
        fed_projections=[],
        treasury=None,
        warnings=[],
    )
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            macro_builder_factory=lambda: builder,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-macro-full",
        store=None,
    )

    result = tools_by_name()["get_macro_snapshot"].func(
        release_type=None,
        runtime=runtime,
    )

    assert [
        release["release_id"]
        for release in result["snapshot"]["recent_releases"]
    ] == [available.release_id]
    statuses = {
        item["target_id"]: item["status"]
        for item in result["quality"]["results"]
    }
    assert statuses == {
        available.release_id: "usable",
        future.release_id: "rejected",
    }


@pytest.mark.parametrize("release_type", [None, "cpi"])
def test_macro_tool_removes_future_metric_from_degraded_release(
    release_type,
):
    as_of = datetime(2026, 9, 20, 16, tzinfo=timezone.utc)
    released_at = datetime(
        2026, 9, 11, 12, 30, tzinfo=timezone.utc
    )
    release = MacroReleaseEvent(
        release_id="cpi:2026-09-11",
        release_type="cpi",
        release_date=date(2026, 9, 11),
        released_at=released_at,
        release_date_source="fixture",
        period_binding="verified",
        metrics=[
            MacroMetricSnapshot(
                indicator="cpi",
                measure="mom",
                unit="percent",
                period=date(2026, 8, 1),
                actual=Decimal("0.3"),
                release_date=date(2026, 9, 11),
                released_at=released_at,
                source="fixture",
                actual_pit_status="verified",
            ),
            MacroMetricSnapshot(
                indicator="cpi",
                measure="yoy",
                unit="percent",
                period=date(2026, 8, 1),
                actual=Decimal("2.9"),
                release_date=date(2026, 9, 21),
                source="fixture",
                actual_pit_status="verified",
            ),
        ],
    )
    builder = Mock()
    builder.build_latest.return_value = MacroSnapshot(
        as_of=as_of,
        recent_releases=[release],
        fed_policy=None,
        fed_projections=[],
        treasury=None,
        warnings=[],
    )
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            macro_builder_factory=lambda: builder,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-macro-sanitize",
        store=None,
    )

    result = tools_by_name()["get_macro_snapshot"].func(
        release_type=release_type,
        runtime=runtime,
    )

    safe_release = (
        result["release"]
        if release_type is not None
        else result["snapshot"]["recent_releases"][0]
    )
    assert [
        metric["measure"]
        for metric in safe_release["metrics"]
    ] == ["mom"]
    assert result["quality"]["overall_status"] == "degraded"
    assert result["quality"]["results"][0]["issues"][0]["code"] == (
        "release_date_after_as_of"
    )


def test_technical_tool_keeps_bars_when_quote_provider_fails():
    as_of = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    provider = Mock()
    provider.get_quote.side_effect = MarketDataProviderError("quote unavailable")
    provider.get_bars.return_value = make_completed_bars(as_of=as_of)
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            market_provider_factory=lambda: provider,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-technical",
        store=None,
    )

    result = asyncio.run(
        tools_by_name()["get_technical_analysis"].coroutine(
            company_id="NVDA",
            runtime=runtime,
        )
    )

    assert result["quote"] is None
    assert result["technical"] is not None
    assert result["quality"]["source_warnings"] == [
        "quote_provider_unavailable"
    ]
    provider.get_bars.assert_called_once_with(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=250,
        include_incomplete=False,
    )


def test_technical_tool_keeps_quote_when_bars_provider_fails():
    as_of = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    quote = Quote(
        symbol="NVDA",
        price=Decimal("187.25"),
        currency="USD",
        quoted_at=as_of - timedelta(seconds=30),
        received_at=as_of - timedelta(seconds=29),
        session="regular",
        data_mode="live",
        is_delayed=None,
        source="longbridge",
    )
    provider = Mock()
    provider.get_quote.return_value = quote
    provider.get_bars.side_effect = MarketDataProviderError("bars unavailable")
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            market_provider_factory=lambda: provider,
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call-technical",
        store=None,
    )

    result = asyncio.run(
        tools_by_name()["get_technical_analysis"].coroutine(
            company_id="NVDA",
            runtime=runtime,
        )
    )

    assert result["quote"] is not None
    assert result["technical"] is None
    assert result["quality"]["source_warnings"] == [
        "bars_provider_unavailable"
    ]
