import asyncio
import inspect
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.messages import AIMessage
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from pydantic import ValidationError

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph import (
    build_initial_state,
    build_research_graph,
)
from stock_agent.agents.langgraph import research
from stock_agent.agents.langgraph.answer import build_answer_messages
from stock_agent.agents.langgraph.checker import (
    checker_node,
    collect_missing_information,
    route_after_check,
)
from stock_agent.agents.langgraph.planner import (
    build_deterministic_plan,
)
from stock_agent.agents.langgraph.state import ResearchPlan
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.earnings import EarningsReleaseEvent
from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.schemas import Quote
from stock_agent.market_reaction.models import MarketReactionResult
from stock_agent.schemas.research import ResearchRequest
from stock_agent.tools import company


AS_OF = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)


def make_request(question: str) -> ResearchRequest:
    return ResearchRequest(
        company_id="NVDA",
        question=question,
        data_mode="mixed",
        as_of=AS_OF,
    )


def make_plan(**updates) -> ResearchPlan:
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


def make_quote() -> Quote:
    return Quote(
        symbol="NVDA",
        price=Decimal("200"),
        currency="USD",
        quoted_at=datetime(
            2026, 10, 8, 7, 59, 30, tzinfo=timezone.utc
        ),
        received_at=datetime(
            2026, 10, 8, 7, 59, 31, tzinfo=timezone.utc
        ),
        session="regular",
        data_mode="live",
        is_delayed=None,
        source="longbridge",
    )


@pytest.mark.parametrize(
    "updates",
    [
        {
            "needs_macro_reaction": True,
        },
        {
            "needs_macro": True,
            "needs_macro_reaction": True,
        },
        {
            "needs_earnings_reaction_history": True,
        },
    ],
)
def test_research_plan_rejects_incomplete_dependencies(updates) -> None:
    with pytest.raises(ValidationError):
        make_plan(**updates)


def test_deterministic_planner_combines_current_history_and_technical() -> None:
    plan = build_deterministic_plan(
        make_request(
            "这次 CPI 发布后 NVDA 怎么走，"
            "之前 3 次 CPI 发布后的表现如何，结合技术面分析"
        )
    )

    assert plan is not None
    assert plan.needs_macro is True
    assert plan.macro_release_type == "cpi"
    assert plan.needs_macro_reaction is True
    assert plan.needs_macro_reaction_history is True
    assert plan.macro_reaction_history_limit == 3
    assert plan.needs_technical is True
    assert plan.needs_decision is True


def test_deterministic_planner_combines_current_and_historical_earnings() -> None:
    plan = build_deterministic_plan(
        make_request(
            "这次财报后怎么走，再看看过去 3 次财报后的表现"
        )
    )

    assert plan is not None
    assert plan.needs_earnings_reaction is True
    assert plan.needs_earnings_reaction_history is True
    assert plan.earnings_reaction_history_limit == 3


def test_checker_retries_provider_failure_only_once() -> None:
    plan = make_plan(needs_quote=True)
    results = {
        "quote": None,
        "market_quality": SimpleNamespace(
            source_warnings=["quote_provider_unavailable"]
        ),
    }
    state = {
        **build_initial_state(make_request("当前股价")),
        "plan": plan,
        "results": results,
    }

    first = checker_node(state)
    assert first == {
        "missing_information": ["quote_unavailable"],
        "research_status": "retry",
    }
    assert route_after_check({**state, **first}) == "research"

    second = checker_node({**state, "retry_count": 1})
    assert second == {
        "missing_information": ["quote_unavailable"],
        "research_status": "cannot_retry",
    }
    assert route_after_check({**state, **second}) == "answer"


def test_checker_treats_empty_requested_history_as_terminal_missing() -> None:
    plan = make_plan(
        needs_earnings_reaction_history=True,
        earnings_reaction_history_limit=3,
    )

    missing = collect_missing_information(
        plan=plan,
        results={"earnings_reaction_history": []},
    )

    assert missing == ["earnings_reaction_history_unavailable"]


def test_macro_latest_reaction_is_awaited(monkeypatch) -> None:
    plan = make_plan(
        needs_macro=True,
        macro_release_type="cpi",
        needs_macro_reaction=True,
    )
    release = MacroReleaseEvent(
        release_id="cpi:2026-09-11",
        release_type="cpi",
        release_date=date(2026, 9, 11),
        released_at=datetime(
            2026, 9, 11, 12, 30, tzinfo=timezone.utc
        ),
        released_at_source="bls",
        release_date_source="bls",
        period_binding="verified",
        metrics=[],
    )
    snapshot = SimpleNamespace(warnings=[])
    macro_provider = Mock()
    macro_provider.build_latest.return_value = snapshot
    reaction = MarketReactionResult(
        release_id=release.release_id,
        release_type="cpi",
        symbol="NVDA",
        event_at=release.released_at,
        reference_price=None,
        reference_at=None,
        observations={},
        issues=[],
    )

    monkeypatch.setattr(
        research,
        "_get_macro_provider",
        AsyncMock(return_value=macro_provider),
    )
    monkeypatch.setattr(
        research,
        "_get_market_provider",
        AsyncMock(return_value=Mock()),
    )
    monkeypatch.setattr(
        research,
        "validate_macro_snapshot",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        research,
        "check_required_macro_releases",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        research,
        "get_latest_release",
        Mock(return_value=release),
    )
    calculate = Mock(return_value=reaction)
    monkeypatch.setattr(
        research,
        "research_event_reaction",
        calculate,
    )

    result = asyncio.run(
        research.research_macro_results(
            plan=plan,
            context=ResearchContext(as_of=AS_OF),
            symbol="NVDA",
        )
    )

    assert result["macro_reaction"] is reaction
    assert not inspect.isawaitable(result["macro_reaction"])
    calculate.assert_called_once()


def test_earnings_research_splits_latest_and_requested_history(
    monkeypatch,
) -> None:
    releases = [
        EarningsReleaseEvent(
            event_id=f"earnings:NVDA:{index}",
            symbol="NVDA",
            released_at=datetime(
                2026, 8 - index, 26, 20, 21, tzinfo=timezone.utc
            ),
            released_at_source="sec_8k_accepted_at",
            report_date=None,
            accession_number=str(index),
            source_url=f"https://www.sec.gov/{index}",
        )
        for index in range(4)
    ]
    get_releases = Mock(return_value=releases)
    latest_reaction = object()
    historical_reactions = [object(), object(), object()]

    monkeypatch.setattr(
        research,
        "get_earnings_releases",
        get_releases,
    )
    monkeypatch.setattr(
        research,
        "_get_market_provider",
        AsyncMock(return_value=Mock()),
    )
    monkeypatch.setattr(
        research,
        "research_earnings_reaction",
        Mock(return_value=latest_reaction),
    )
    history = Mock(return_value=historical_reactions)
    monkeypatch.setattr(
        research,
        "research_earnings_reactions",
        history,
    )

    result = asyncio.run(
        research.research_earnings_results(
            plan=make_plan(
                needs_earnings_reaction=True,
                needs_earnings_reaction_history=True,
                earnings_reaction_history_limit=3,
            ),
            request=make_request("这次和过去三次财报后的表现"),
            context=ResearchContext(as_of=AS_OF),
        )
    )

    get_releases.assert_called_once_with(
        symbol="NVDA",
        as_of=AS_OF,
        limit=4,
    )
    assert result["earnings_release"] is releases[0]
    assert result["earnings_release_history"] == releases[1:]
    assert result["earnings_reaction"] is latest_reaction
    assert result["earnings_reaction_history"] == historical_reactions
    assert history.call_args.kwargs["earnings"] == releases[1:]


def test_knowledge_research_uses_exact_planned_question(monkeypatch) -> None:
    retrieve = Mock(return_value=[{"content": "data center growth"}])
    monkeypatch.setattr(research, "retrieve_knowledge", retrieve)
    engine = Mock()
    context = ResearchContext(as_of=AS_OF, engine=engine)

    result = asyncio.run(
        research.research_knowledge_results(
            plan=make_plan(
                knowledge_question="管理层如何解释数据中心增长？"
            ),
            context=context,
            company_id=" nvda ",
        )
    )

    assert result == {
        "knowledge": [{"content": "data center growth"}]
    }
    retrieve.assert_called_once_with(
        "NVDA",
        "管理层如何解释数据中心增长？",
        AS_OF,
        engine=engine,
        config=context.index_config,
    )


def test_answer_payload_serializes_dataclass_results() -> None:
    earnings = EarningsReleaseEvent(
        event_id="earnings:NVDA:0001",
        symbol="NVDA",
        released_at=datetime(
            2026, 8, 26, 20, 21, tzinfo=timezone.utc
        ),
        released_at_source="sec_8k_accepted_at",
        report_date=date(2026, 8, 26),
        accession_number="0001",
        source_url="https://www.sec.gov/example",
    )
    state = {
        **build_initial_state(make_request("最近财报后怎么走")),
        "plan": make_plan(needs_earnings_reaction=True),
        "results": {"earnings_release": earnings},
        "research_status": "enough",
    }

    messages = build_answer_messages(state)
    payload = json.loads(messages[1].content)

    assert payload["results"]["earnings_release"]["report_date"] == (
        "2026-08-26"
    )
    assert payload["results"]["earnings_release"]["released_at"] == (
        "2026-08-26T20:21:00+00:00"
    )


def test_sec_company_profile_is_separate_from_fixture_tool(monkeypatch) -> None:
    monkeypatch.setattr(
        company,
        "ticker_to_cik",
        Mock(return_value="0001045810"),
    )
    monkeypatch.setattr(
        company,
        "get_company_submissions",
        Mock(
            return_value={
                "name": "NVIDIA CORP",
                "tickers": ["NVDA"],
            }
        ),
    )

    live = company.get_sec_company_profile(" nvda ")
    fixture = company.get_company_profile("NVDA")

    assert live["company_name"] == "NVIDIA CORP"
    assert live["data_mode"] == "live"
    assert fixture["data_mode"] == "fixture"


def test_graph_runs_only_planned_quote_path() -> None:
    provider = Mock()
    provider.get_quote.return_value = make_quote()
    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="NVDA 当前报价为 200 USD。")]
    )
    graph = build_research_graph(model)
    request = make_request("NVDA 当前股价是多少？")

    result = asyncio.run(
        graph.ainvoke(
            build_initial_state(request),
            context=ResearchContext(
                as_of=AS_OF,
                market_provider_factory=Mock(return_value=provider),
            ),
        )
    )

    assert result["research_status"] == "enough"
    assert result["retry_count"] == 0
    assert result["output"] == "NVDA 当前报价为 200 USD。"
    assert result["results"]["quote"] == make_quote()
    assert "technical" not in result["results"]
    assert "macro_snapshot" not in result["results"]
    provider.get_quote.assert_called_once()
    provider.get_bars.assert_not_called()


def test_graph_stops_after_one_failed_quote_retry() -> None:
    provider = Mock()
    provider.get_quote.side_effect = MarketDataProviderError("temporary")
    provider_factory = Mock(return_value=provider)
    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="报价暂时不可用。")]
    )
    graph = build_research_graph(model)
    request = make_request("NVDA 当前股价是多少？")

    result = asyncio.run(
        graph.ainvoke(
            build_initial_state(request),
            context=ResearchContext(
                as_of=AS_OF,
                market_provider_factory=provider_factory,
            ),
        )
    )

    assert result["research_status"] == "cannot_retry"
    assert result["retry_count"] == 1
    assert result["missing_information"] == ["quote_unavailable"]
    assert result["output"] == "报价暂时不可用。"
    assert provider.get_quote.call_count == 2
