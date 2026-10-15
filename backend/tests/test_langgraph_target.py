"""D38：Target Resolver、澄清中断与恢复流程验收。"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

from langchain.messages import AIMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph.graph import (
    build_initial_state,
    build_research_graph,
)
from stock_agent.agents.langgraph.planner import (
    plan_requires_security_target,
    route_after_plan,
)
from stock_agent.agents.langgraph.state import ResearchPlan, ResearchState
from stock_agent.agents.langgraph import target
from stock_agent.company import resolver
from stock_agent.company.registry import SecurityRecord
from stock_agent.company.resolver import AmbiguousTarget, TargetResolution
from stock_agent.market.schemas import Quote
from stock_agent.schemas.research import ResearchRequest


AS_OF = datetime(2026, 10, 10, 16, tzinfo=timezone.utc)


class AnswerOnlyModel:
    def with_structured_output(self, schema):
        raise AssertionError("deterministic target and planner must not call the model")

    async def ainvoke(self, messages):
        return AIMessage(content="NVDA 当前报价已返回。")


def make_request(
    question: str,
    *,
    company_ids: list[str] | None = None,
) -> ResearchRequest:
    return ResearchRequest(
        company_ids=company_ids or [],
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
    return ResearchPlan.model_validate(values)


def install_security_registry(monkeypatch) -> None:
    def lookup_security(symbol, *, fallback_provider_factory):
        normalized = symbol.strip().upper()
        if normalized not in {"NVDA", "AAPL"}:
            return None
        return SecurityRecord(
            symbol=normalized,
            name=normalized,
            cik="0000000001",
        )

    monkeypatch.setattr(
        resolver,
        "lookup_security",
        lookup_security,
    )


def test_pre_resolved_request_skips_target_model(monkeypatch) -> None:
    async def unexpected_resolver(*args, **kwargs):
        raise AssertionError("pre-resolved request must not run Target Resolver")

    monkeypatch.setattr(target, "resolve_targets", unexpected_resolver)
    state = build_initial_state(
        make_request("查询报价", company_ids=["nvda"])
    )
    runtime = cast(
        Runtime[ResearchContext],
        SimpleNamespace(context=ResearchContext(as_of=AS_OF)),
    )

    update = asyncio.run(
        target.resolve_target_node(
            state,
            runtime,
            model=cast(BaseChatModel, AnswerOnlyModel()),
        )
    )

    request = cast(ResearchRequest, update["request"])
    resolution = cast(TargetResolution, update["target_resolution"])
    assert request.company_ids == ["NVDA"]
    assert resolution.status == "resolved"


def test_clarification_resolution_accumulates_company_ids(monkeypatch) -> None:
    def lookup_security(symbol, *, fallback_provider_factory):
        assert symbol == "AAPL"
        return SecurityRecord(
            symbol="AAPL",
            name="Apple Inc.",
            cik="0000320193",
        )

    monkeypatch.setattr(target, "lookup_security", lookup_security)
    state = build_initial_state(
        make_request("Google 怎么看", company_ids=["NVDA"])
    )
    state["target_clarification"] = ["AAPL"]
    runtime = cast(
        Runtime[ResearchContext],
        SimpleNamespace(context=ResearchContext(as_of=AS_OF)),
    )

    update = asyncio.run(
        target.resolve_target_node(
            state,
            runtime,
            model=cast(BaseChatModel, AnswerOnlyModel()),
        )
    )

    request = cast(ResearchRequest, update["request"])
    resolution = cast(TargetResolution, update["target_resolution"])
    assert request.question == "Google 怎么看"
    assert request.company_ids == ["NVDA", "AAPL"]
    assert resolution.resolved_targets == ["NVDA", "AAPL"]


def test_clarification_accepts_structured_ticker_list() -> None:
    workflow = StateGraph(ResearchState)
    workflow.add_node("clarify_target", target.clarify_target_node)
    workflow.add_edge(START, "clarify_target")
    workflow.add_edge("clarify_target", END)
    graph = workflow.compile(checkpointer=InMemorySaver())
    config = RunnableConfig(
        configurable={"thread_id": "structured-clarification-test"}
    )
    state = build_initial_state(make_request("Google 怎么看"))
    state["target_resolution"] = TargetResolution(
        ambiguous_targets=[
            AmbiguousTarget(
                mention="Google",
                candidates=["GOOG", "GOOGL"],
            )
        ]
    )

    interrupted = graph.invoke(state, config=config)
    assert interrupted["__interrupt__"][0].value["type"] == "target_clarification"

    resumed = graph.invoke(Command(resume=["GOOGL"]), config=config)
    assert resumed["target_clarification"] == ["GOOGL"]


def test_plan_routes_macro_only_without_target_and_security_to_clarify() -> None:
    macro_state = build_initial_state(make_request("最新 CPI 是多少"))
    macro_state["plan"] = make_plan(
        needs_macro=True,
        macro_release_type="cpi",
    )

    assert plan_requires_security_target(macro_state["plan"]) is False
    assert route_after_plan(macro_state) == "research"

    quote_state = build_initial_state(make_request("查询当前报价"))
    quote_state["plan"] = make_plan(needs_quote=True)

    assert plan_requires_security_target(quote_state["plan"]) is True
    assert route_after_plan(quote_state) == "clarify_target"


def test_graph_researches_multiple_resolved_targets_without_interrupt(
    monkeypatch,
) -> None:
    install_security_registry(monkeypatch)
    provider = Mock()
    def get_quote(*, symbol: str, as_of: datetime) -> Quote:
        return Quote(
            symbol=symbol,
            price=Decimal("195.25"),
            currency="USD",
            quoted_at=AS_OF - timedelta(seconds=30),
            received_at=AS_OF - timedelta(seconds=29),
            session="regular",
            data_mode="live",
            is_delayed=False,
            source="longbridge",
        )

    provider.get_quote.side_effect = get_quote
    context = ResearchContext(
        as_of=AS_OF,
        market_provider_factory=lambda: provider,
    )
    graph = build_research_graph(
        cast(BaseChatModel, AnswerOnlyModel()),
        checkpointer=InMemorySaver(),
    )
    config = RunnableConfig(
        configurable={"thread_id": "target-resume-test"}
    )

    completed = asyncio.run(
        graph.ainvoke(
            build_initial_state(
                make_request("比较 NVDA 和 AAPL 的当前报价")
            ),
            context=context,
            config=config,
        )
    )

    assert "__interrupt__" not in completed
    assert completed["request"].company_ids == ["NVDA", "AAPL"]
    assert completed["target_resolution"].status == "resolved"
    assert completed["output"] == "NVDA 当前报价已返回。"
    assert provider.get_quote.call_count == 2
    provider.get_quote.assert_any_call(symbol="NVDA", as_of=AS_OF)
    provider.get_quote.assert_any_call(symbol="AAPL", as_of=AS_OF)
