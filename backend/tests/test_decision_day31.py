from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from stock_agent.decision.builder import build_market_context
from stock_agent.decision.models import (
    MARKET_CONTEXT_VERSION,
    DecisionResult,
    FactorEvidence,
    FactorOpinion,
    MarketContext,
)
from stock_agent.macro.calculations.treasury import build_treasury_snapshot
from stock_agent.macro.models.metric import MacroMetricSnapshot
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.models.snapshot import MacroSnapshot
from stock_agent.macro.models.treasury import TreasuryYield
from stock_agent.macro.release_builders import build_macro_release
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.schemas import Quote
from stock_agent.market_reaction.service import research_event_reaction


AS_OF = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def make_quote(*, symbol: str = "NVDA", quoted_at: datetime | None = None) -> Quote:
    event_at = quoted_at or AS_OF - timedelta(minutes=1)
    return Quote(
        symbol=symbol,
        price=Decimal("100"),
        currency="USD",
        quoted_at=event_at,
        received_at=event_at,
        session="regular",
        data_mode="fixture",
        is_delayed=False,
        source="fixture-market",
    )


def make_release(
    *,
    release_id: str,
    released_at: datetime | None,
) -> MacroReleaseEvent:
    return MacroReleaseEvent(
        release_id=release_id,
        release_type="cpi",
        release_date=date(2026, 9, 30),
        scheduled_release_at=AS_OF - timedelta(hours=4),
        released_at=released_at,
        released_at_source="bls",
        release_date_source="bls",
        schedule_source="bls",
        period_binding="verified",
        metrics=[],
    )


def make_metric() -> MacroMetricSnapshot:
    return MacroMetricSnapshot(
        indicator="cpi",
        measure="mom",
        unit="percent",
        period=date(2026, 8, 1),
        actual=Decimal("0.4"),
        release_date=date(2026, 9, 30),
        source="bls",
    )


def test_build_market_context_defaults_version_and_reports_missing_components() -> None:
    context = build_market_context(
        symbol=" nvda ",
        as_of=AS_OF,
        requested_components={"quote", "macro"},
    )

    assert context.symbol == "NVDA"
    assert context.context_version == MARKET_CONTEXT_VERSION
    assert "context_versionLiteral" not in MarketContext.model_fields
    assert context.component_statuses == {
        "quote": "missing",
        "technical": "not_requested",
        "macro": "missing",
        "market_reaction": "not_requested",
    }
    assert context.missing_components == ["quote", "macro"]


def test_market_context_version_is_fixed_contract() -> None:
    with pytest.raises(ValidationError):
        MarketContext(
            symbol="NVDA",
            as_of=AS_OF,
            requested_components={"quote"},
            context_version="unexpected-version",
        )


def test_market_context_records_quote_source_and_rejects_future_quote() -> None:
    context = build_market_context(
        symbol="NVDA",
        as_of=AS_OF,
        requested_components={"quote"},
        quote=make_quote(),
    )

    assert context.component_statuses["quote"] == "available"
    assert context.provenance.components["quote"].sources == (
        "fixture-market",
    )

    with pytest.raises(ValueError, match="quote timestamp is after context as_of"):
        build_market_context(
            symbol="NVDA",
            as_of=AS_OF,
            requested_components={"quote"},
            quote=make_quote(quoted_at=AS_OF + timedelta(seconds=1)),
        )


def test_macro_validation_checks_releases_after_missing_time_entry() -> None:
    macro = MacroSnapshot(
        as_of=AS_OF,
        recent_releases=[
            make_release(release_id="cpi:missing-time", released_at=None),
            make_release(
                release_id="cpi:future",
                released_at=AS_OF + timedelta(minutes=1),
            ),
        ],
        fed_policy=None,
        fed_projections=[],
        treasury=None,
        warnings=[],
    )

    with pytest.raises(ValueError, match="macro release is after macro as_of"):
        build_market_context(
            symbol="NVDA",
            as_of=AS_OF,
            requested_components={"macro"},
            macro=macro,
        )


def test_macro_release_preserves_actual_time_source() -> None:
    release = build_macro_release(
        release_type="cpi",
        release_date=date(2026, 9, 30),
        metrics=[make_metric()],
        release_date_source="fred",
        released_at=AS_OF - timedelta(hours=4),
        released_at_source="bls",
    )

    assert release.released_at_source == "bls"


def test_market_reaction_preserves_event_time_source_on_provider_failure() -> None:
    release = make_release(
        release_id="cpi:2026-09-30",
        released_at=AS_OF - timedelta(hours=4),
    )
    provider = FixtureMarketDataProvider(quotes={}, bars={})

    result = research_event_reaction(
        release=release,
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    assert result.event_time_source == "bls"


def test_single_treasury_curve_records_sources_without_previous_curve() -> None:
    observations = [
        TreasuryYield(
            observation_date=date(2026, 9, 29),
            tenor=tenor,
            yield_pct=Decimal(value),
            source="fred_h15",
        )
        for tenor, value in zip(
            ("3m", "2y", "10y", "30y"),
            ("4.00", "3.70", "3.90", "4.20"),
        )
    ]

    snapshot = build_treasury_snapshot(
        observations=observations,
        as_of=date(2026, 9, 30),
    )

    assert snapshot is not None
    assert snapshot.previous_yield_sources is None
    assert set(snapshot.yield_sources.values()) == {"fred_h15"}


def test_factor_and_decision_contracts() -> None:
    factor = FactorOpinion(
        factor="trend",
        status="usable",
        signal="bullish",
        rule_version="trend-v1",
        evidence=[
            FactorEvidence(
                metric="ma5",
                value=Decimal("105"),
                source="technical.ma5",
            )
        ],
        reasons=["ma5_above_ma20"],
    )
    decision = DecisionResult(
        symbol=" nvda ",
        as_of=AS_OF,
        status="complete",
        market_view="bullish",
        rule_version="decision-v1",
        factors=[factor],
    )

    assert decision.symbol == "NVDA"
    assert decision.factors == [factor]

    with pytest.raises(ValueError, match="usable factor requires signal"):
        FactorOpinion(
            factor="trend",
            status="usable",
            rule_version="trend-v1",
            reasons=["ma5_above_ma20"],
        )

    with pytest.raises(ValueError, match="blocked decision must not"):
        DecisionResult(
            symbol="NVDA",
            as_of=AS_OF,
            status="blocked",
            market_view="neutral",
            rule_version="decision-v1",
        )

    with pytest.raises(ValueError, match="duplicate factor opinion"):
        DecisionResult(
            symbol="NVDA",
            as_of=AS_OF,
            status="complete",
            market_view="bullish",
            rule_version="decision-v1",
            factors=[factor, factor],
        )
