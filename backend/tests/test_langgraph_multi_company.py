"""Multi-security Research result and Checker contract tests."""

from types import SimpleNamespace

from stock_agent.agents.langgraph.checker import (
    collect_missing_information,
    split_missing_information,
)
from stock_agent.agents.langgraph.state import FinancialResearchRequest, ResearchPlan


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
    return ResearchPlan.model_validate(values)


def test_checker_reports_missing_data_for_the_affected_company_only() -> None:
    missing = collect_missing_information(
        plan=make_plan(needs_quote=True),
        company_ids=["NVDA", "AAPL"],
        results={
            "companies": {
                "NVDA": {"quote": {"price": "200"}},
                "AAPL": {"quote": None},
            }
        },
    )

    assert missing == ["quote_unavailable:AAPL"]


def test_shared_macro_snapshot_is_checked_once_without_a_company() -> None:
    missing = collect_missing_information(
        plan=make_plan(needs_macro=True),
        company_ids=[],
        results={"macro_snapshot": object()},
    )

    assert missing == []


def test_shared_macro_unavailable_uses_the_expected_reason() -> None:
    missing = collect_missing_information(
        plan=make_plan(needs_macro=True),
        company_ids=[],
        results={"macro_snapshot": None},
    )

    assert missing == ["macro_snapshot_unavailable"]


def test_financial_missing_item_keeps_company_and_concept_separate() -> None:
    plan = make_plan(
        financial_requests=[
            FinancialResearchRequest(
                concept="Revenue",
                unit="USD",
                period_type="quarterly",
            )
        ]
    )
    missing = collect_missing_information(
        plan=plan,
        company_ids=["NVDA"],
        results={"companies": {"NVDA": {"financial": []}}},
    )

    assert missing == ["financial_request_not_executed:NVDA:Revenue"]

    retryable, terminal = split_missing_information(
        missing_information=missing,
        results={"companies": {"NVDA": {}}},
    )
    assert retryable == missing
    assert terminal == []


def test_retry_warning_is_scoped_to_matching_company() -> None:
    retryable, terminal = split_missing_information(
        missing_information=[
            "quote_unavailable:NVDA",
            "quote_unavailable:AAPL",
        ],
        results={
            "companies": {
                "NVDA": {
                    "market_quality": SimpleNamespace(
                        source_warnings=["quote_provider_unavailable"]
                    )
                },
                "AAPL": {
                    "market_quality": SimpleNamespace(source_warnings=[])
                },
            }
        },
    )

    assert retryable == ["quote_unavailable:NVDA"]
    assert terminal == ["quote_unavailable:AAPL"]
