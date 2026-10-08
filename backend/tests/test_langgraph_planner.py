from datetime import datetime, timezone

from stock_agent.agents.langgraph.planner import build_deterministic_plan
from stock_agent.schemas.research import ResearchRequest


def test_deterministic_plan_combines_technical_and_decision() -> None:
    request = ResearchRequest(
        company_id="NVDA",
        question="NVDA 当前走势怎么看，同时告诉我 RSI14",
        data_mode="live",
        as_of=datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc),
    )

    plan = build_deterministic_plan(request)

    assert plan is not None
    assert plan.needs_technical is True
    assert plan.needs_decision is True


def test_deterministic_plan_recognizes_macro_reaction_word_order() -> None:
    request = ResearchRequest(
        company_id="NVDA",
        question="最近一次 CPI 后 NVDA 怎么走？",
        data_mode="mixed",
        as_of=datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc),
    )

    plan = build_deterministic_plan(request)

    assert plan is not None
    assert plan.needs_macro is True
    assert plan.macro_release_type == "cpi"
    assert plan.needs_macro_reaction is True
