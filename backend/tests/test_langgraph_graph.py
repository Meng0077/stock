import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from langchain.messages import AIMessage
from langchain_core.language_models import BaseChatModel
from langgraph.runtime import Runtime

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph import graph as graph_module
from stock_agent.agents.langgraph.checker import (
    checker_node as real_checker_node,
)
from stock_agent.agents.langgraph.graph import (
    build_initial_state,
    build_research_graph,
)
from stock_agent.agents.langgraph.state import ResearchPlan, ResearchState
from stock_agent.market.schemas import Bar, Quote
from stock_agent.schemas.research import ResearchRequest


AS_OF = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def make_request(question: str) -> ResearchRequest:
    return ResearchRequest(
        company_id="NVDA",
        question=question,
        data_mode="live",
        as_of=AS_OF,
    )


def make_plan(**updates: object) -> ResearchPlan:
    values = {
        "needs_company_profile": False,
        "needs_quote": False,
        "needs_technical": False,
        "needs_decision": False,
        "knowledge_question": None,
        "financial_requests": [],
        "needs_macro": False,
        "macro_release_type": None,
        "needs_macro_reaction": False,
        "needs_macro_reaction_history": False,
        "macro_reaction_history_limit": None,
        "needs_earnings_reaction": False,
        "needs_earnings_reaction_history": False,
        "earnings_reaction_history_limit": None,
    }
    values.update(updates)
    return ResearchPlan(**values)


def make_quote(*, price: str = "200.00") -> Quote:
    return Quote(
        symbol="NVDA",
        price=Decimal(price),
        currency="USD",
        quoted_at=AS_OF - timedelta(seconds=10),
        received_at=AS_OF - timedelta(seconds=5),
        session="regular",
        data_mode="live",
        is_delayed=False,
        source="test_provider",
    )


def make_daily_bars(*, count: int = 220) -> list[Bar]:
    first_start = AS_OF - timedelta(days=count + 1)
    bars = []

    for index in range(count):
        start_at = first_start + timedelta(days=index)
        end_at = start_at + timedelta(hours=6)
        close = Decimal("100") + Decimal(index) * Decimal("0.50")
        open_price = close - Decimal("0.20")

        bars.append(
            Bar(
                symbol="NVDA",
                timeframe="1d",
                start_at=start_at,
                end_at=end_at,
                open=open_price,
                high=close + Decimal("0.50"),
                low=open_price - Decimal("0.50"),
                close=close,
                volume=1_000_000,
                is_complete=True,
                adjustment="raw",
                updated_at=end_at,
                received_at=end_at + timedelta(minutes=1),
                source="test_provider",
                data_mode="live",
            )
        )

    return bars


def test_graph_runs_planner_research_checker_answer(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_plan_node(
        state: ResearchState,
        *,
        model: Any,
    ) -> dict[str, ResearchPlan]:
        calls.append("planner")
        assert state["request"].company_id == "NVDA"
        return {"plan": make_plan(needs_quote=True)}

    async def fake_research_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
    ) -> dict[str, object]:
        calls.append("research")
        assert state["plan"] is not None
        assert runtime.context.as_of == AS_OF
        return {
            "results": {
                "quote": {
                    "symbol": "NVDA",
                    "price": 200.0,
                },
            },
        }

    def fake_checker_node(state: ResearchState) -> dict[str, object]:
        calls.append("checker")
        quote = cast(dict[str, object], state["results"]["quote"])
        assert quote["price"] == 200.0
        return {
            "missing_information": [],
            "research_status": "enough",
        }

    async def fake_answer_node(
        state: ResearchState,
        *,
        model: Any,
    ) -> dict[str, str]:
        calls.append("answer")
        assert state["research_status"] == "enough"
        return {"output": "NVDA 当前报价为 200 USD。"}

    monkeypatch.setattr(graph_module, "plan_node", fake_plan_node)
    monkeypatch.setattr(graph_module, "research_node", fake_research_node)
    monkeypatch.setattr(graph_module, "checker_node", fake_checker_node)
    monkeypatch.setattr(graph_module, "answer_node", fake_answer_node)

    graph = graph_module.build_research_graph(
        cast(BaseChatModel, Mock())
    )
    result = asyncio.run(
        graph.ainvoke(
            build_initial_state(make_request("NVDA 现在多少钱？")),
            context=ResearchContext(as_of=AS_OF),
        )
    )

    assert calls == ["planner", "research", "checker", "answer"]
    assert result["research_status"] == "enough"
    assert result["results"] == {
        "quote": {
            "symbol": "NVDA",
            "price": 200.0,
        },
    }
    assert result["output"] == "NVDA 当前报价为 200 USD。"


def test_graph_retries_research_then_answers(monkeypatch) -> None:
    calls: list[str] = []
    research_count = 0

    async def fake_plan_node(
        state: ResearchState,
        *,
        model: Any,
    ) -> dict[str, ResearchPlan]:
        calls.append("planner")
        return {"plan": make_plan(needs_quote=True)}

    async def fake_research_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
    ) -> dict[str, object]:
        nonlocal research_count
        research_count += 1
        calls.append("research")
        assert runtime.context.as_of == AS_OF

        retry_count = state.get("retry_count", 0)
        if state.get("research_status") == "retry":
            retry_count += 1

        if research_count == 1:
            return {
                "results": {
                    "quote": None,
                    "market_quality": SimpleNamespace(
                        source_warnings=["quote_provider_unavailable"]
                    ),
                },
                "retry_count": retry_count,
            }

        return {
            "results": {
                "quote": {
                    "symbol": "NVDA",
                    "price": 200.0,
                },
                "market_quality": SimpleNamespace(source_warnings=[]),
            },
            "retry_count": retry_count,
        }

    def recording_checker_node(
        state: ResearchState,
    ) -> dict[str, object]:
        calls.append("checker")
        return real_checker_node(state)

    async def fake_answer_node(
        state: ResearchState,
        *,
        model: Any,
    ) -> dict[str, str]:
        calls.append("answer")
        assert state["research_status"] == "enough"
        assert state["retry_count"] == 1
        return {"output": "NVDA 当前报价为 200 USD。"}

    monkeypatch.setattr(graph_module, "plan_node", fake_plan_node)
    monkeypatch.setattr(graph_module, "research_node", fake_research_node)
    monkeypatch.setattr(
        graph_module,
        "checker_node",
        recording_checker_node,
    )
    monkeypatch.setattr(graph_module, "answer_node", fake_answer_node)

    graph = graph_module.build_research_graph(
        cast(BaseChatModel, Mock())
    )
    result = asyncio.run(
        graph.ainvoke(
            build_initial_state(make_request("NVDA 现在多少钱？")),
            context=ResearchContext(as_of=AS_OF),
        )
    )

    assert calls == [
        "planner",
        "research",
        "checker",
        "research",
        "checker",
        "answer",
    ]
    assert research_count == 2
    assert result["research_status"] == "enough"
    assert result["retry_count"] == 1
    assert result["missing_information"] == []
    quote = cast(dict[str, object], result["results"]["quote"])
    assert quote["price"] == 200.0
    assert result["output"] == "NVDA 当前报价为 200 USD。"


def test_graph_runs_real_quote_workflow() -> None:
    class FakeQuoteProvider:
        def __init__(self, quote: Quote):
            self.quote = quote
            self.quote_calls = 0
            self.bar_calls = 0

        def get_quote(self, symbol: str, *, as_of: datetime) -> Quote:
            self.quote_calls += 1
            assert symbol == "NVDA"
            assert as_of == AS_OF
            return self.quote

        def get_bars(self, *args: object, **kwargs: object) -> list[Bar]:
            self.bar_calls += 1
            raise AssertionError("quote-only research must not request bars")

        def get_intraday_bars(
            self,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            raise AssertionError(
                "quote-only research must not request intraday bars"
            )

    quote = make_quote()
    provider = FakeQuoteProvider(quote)
    model = Mock()
    model.ainvoke = AsyncMock(
        return_value=AIMessage(content="NVDA 当前报价为 200 USD。")
    )
    graph = build_research_graph(model)

    result = asyncio.run(
        graph.ainvoke(
            build_initial_state(make_request("NVDA 现在多少钱？")),
            context=ResearchContext(
                as_of=AS_OF,
                market_provider_factory=lambda: provider,
                market_state="trading",
            ),
        )
    )

    assert result["plan"].needs_quote is True
    assert result["plan"].needs_technical is False
    assert result["plan"].needs_decision is False
    assert result["results"]["quote"] == quote
    assert result["research_status"] == "enough"
    assert result["missing_information"] == []
    assert result["retry_count"] == 0
    assert result["output"] == "NVDA 当前报价为 200 USD。"
    assert provider.quote_calls == 1
    assert provider.bar_calls == 0
    model.ainvoke.assert_awaited_once()

    messages = model.ainvoke.await_args.args[0]
    payload = json.loads(messages[1].content)
    assert payload["results"]["quote"]["symbol"] == "NVDA"
    assert payload["results"]["quote"]["price"] == "200.00"
    assert payload["research_status"] == "enough"


def test_graph_shares_market_load_for_technical_and_decision() -> None:
    class FakeMarketAnalysisProvider:
        def __init__(self, quote: Quote, bars: list[Bar]):
            self.quote = quote
            self.bars = bars
            self.quote_calls = 0
            self.bar_calls = 0

        def get_quote(self, symbol: str, *, as_of: datetime) -> Quote:
            self.quote_calls += 1
            assert symbol == "NVDA"
            assert as_of == AS_OF
            return self.quote

        def get_bars(
            self,
            symbol: str,
            *,
            as_of: datetime,
            timeframe: str,
            limit: int,
            include_incomplete: bool = False,
            adjustment: object = None,
        ) -> list[Bar]:
            self.bar_calls += 1
            assert symbol == "NVDA"
            assert as_of == AS_OF
            assert timeframe == "1d"
            assert limit == 250
            assert include_incomplete is False
            return self.bars

        def get_intraday_bars(
            self,
            *args: object,
            **kwargs: object,
        ) -> list[object]:
            raise AssertionError(
                "technical decision research must not request intraday bars"
            )

    provider = FakeMarketAnalysisProvider(
        quote=make_quote(price="210.00"),
        bars=make_daily_bars(),
    )
    model = Mock()
    model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                "NVDA 当前技术结构已有确定性研究结果，"
                "RSI14 等具体指标也已提供。"
            )
        )
    )
    graph = build_research_graph(model)

    result = asyncio.run(
        graph.ainvoke(
            build_initial_state(
                make_request("NVDA 当前走势怎么看，同时告诉我 RSI14")
            ),
            context=ResearchContext(
                as_of=AS_OF,
                market_provider_factory=lambda: provider,
                market_state="trading",
            ),
        )
    )

    plan = result["plan"]
    assert plan.needs_technical is True
    assert plan.needs_decision is True

    technical = result["results"]["technical"]
    decision = result["results"]["decision"]
    assert technical is not None
    assert technical.rsi14 is not None
    assert decision is not None
    assert decision.status != "blocked"
    assert result["research_status"] == "enough"
    assert result["missing_information"] == []
    assert provider.quote_calls == 1
    assert provider.bar_calls == 1
    model.ainvoke.assert_awaited_once()
