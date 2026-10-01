from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from stock_agent.decision.engine import evaluate_market
from stock_agent.decision.models import DecisionResult, MarketContext
from stock_agent.market.price_structure import PriceLevel, PriceStructureSnapshot
from stock_agent.market.technical import MarketTechnicalSnapshot
from stock_agent.market.volume import VolumeFeatures


AS_OF = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def make_level(price: str, *, atr_distance: str) -> PriceLevel:
    value = Decimal(price)
    return PriceLevel(
        price=value,
        lower_bound=value,
        upper_bound=value,
        touches=2,
        first_touch_at=AS_OF,
        last_touch_at=AS_OF,
        price_distance=None,
        atr_distance=Decimal(atr_distance),
    )


def make_structure(
    *,
    recent_high: str = "110",
    recent_low: str = "90",
    support: list[PriceLevel] | None = None,
    resistance: list[PriceLevel] | None = None,
) -> PriceStructureSnapshot:
    return PriceStructureSnapshot(
        recent_high_20d=Decimal(recent_high),
        recent_low_20d=Decimal(recent_low),
        previous_swing_high=None,
        previous_swing_low=None,
        support_candidates=support or [],
        resistance_candidates=resistance or [],
        current_zone=None,
        active_gaps=[],
        fibonacci=None,
    )


def make_context(
    *,
    current_price: str = "100",
    ma20: str = "95",
    ma50: str = "90",
    ma20_slope: str = "1",
    ma50_slope: str = "0.5",
    return_5d: str = "2",
    return_20d: str = "5",
    rsi14: str = "60",
    structure: PriceStructureSnapshot | None = None,
) -> MarketContext:
    price = Decimal(current_price)
    technical = MarketTechnicalSnapshot(
        symbol="NVDA",
        calculation_version="technical-v1",
        input_sources=("fixture",),
        current_price=price,
        price_source="completed_close",
        price_at=AS_OF,
        latest_completed_close=price,
        ma5=None,
        ma20=Decimal(ma20),
        ma50=Decimal(ma50),
        ma200=None,
        ma20_slope_5d_pct=Decimal(ma20_slope),
        ma50_slope_5d_pct=Decimal(ma50_slope),
        return_5d_pct=Decimal(return_5d),
        return_20d_pct=Decimal(return_20d),
        rsi14=Decimal(rsi14),
        atr14=Decimal("10"),
        price_structure=structure or make_structure(),
        current_bar_structure=None,
        volume_features=VolumeFeatures(
            latest_completed_at=None,
            latest_volume=None,
            volume_adjustment="provider_reported",
            baseline_volume_20d=None,
            avg_volume_5d=None,
            rvol=None,
            volume_trend_ratio=None,
        ),
    )
    return MarketContext(
        symbol="NVDA",
        as_of=AS_OF,
        requested_components={"technical"},
        technical=technical,
    )


def evidence_by_metric(result: DecisionResult, factor_name: str) -> dict:
    factor = next(
        item for item in result.factors if item.factor == factor_name
    )
    return {item.metric: item for item in factor.evidence}


def test_trace_preserves_indicator_threshold_and_price_source() -> None:
    result = evaluate_market(make_context())
    trend_evidence = evidence_by_metric(result, "trend")
    momentum_evidence = evidence_by_metric(result, "momentum")

    assert result.decision_reasons == [
        "primary_factors_aligned",
        "level_no_directional_override",
    ]
    assert trend_evidence["current_price"].value == Decimal("100")
    assert trend_evidence["current_price"].source == "technical.current_price"
    assert trend_evidence["current_price_source"].value == "completed_close"
    assert trend_evidence["slope_direction_threshold_pct"].value == Decimal(
        "0"
    )
    assert momentum_evidence["return_direction_threshold_pct"].value == Decimal(
        "0"
    )
    assert momentum_evidence["rsi_overbought_threshold"].value == Decimal("70")
    assert momentum_evidence["rsi_midpoint"].value == Decimal("50")
    assert momentum_evidence["rsi_oversold_threshold"].value == Decimal("30")


def test_bullish_trace_records_unconfirmed_momentum_and_near_resistance() -> None:
    result = evaluate_market(
        make_context(
            return_5d="2",
            return_20d="-1",
            structure=make_structure(
                resistance=[make_level("102", atr_distance="0.2")],
            ),
        )
    )

    assert result.market_view == "bullish"
    assert result.decision_reasons == [
        "trend_direction_retained_without_momentum_confirmation",
        "level_no_directional_override",
    ]
    assert result.opposing_reasons == [
        "momentum_not_confirmed",
        "momentum_horizons_not_aligned",
        "near_resistance",
    ]
    assert result.invalidation_conditions == [
        "price_not_above_ma20",
        "ma20_not_above_ma50",
        "ma20_slope_non_positive",
        "ma50_slope_non_positive",
        "momentum_turns_bearish",
        "price_breaks_below_20d_low",
    ]
    level_evidence = evidence_by_metric(result, "level")
    assert level_evidence["near_level_atr_threshold"].value == Decimal("0.5")


def test_bearish_trace_records_near_support_as_opposing_reason() -> None:
    result = evaluate_market(
        make_context(
            current_price="80",
            ma20="90",
            ma50="100",
            ma20_slope="-1",
            ma50_slope="-0.5",
            return_5d="-2",
            return_20d="-5",
            rsi14="25",
            structure=make_structure(
                recent_low="70",
                support=[make_level("78", atr_distance="0.2")],
            ),
        )
    )

    assert result.market_view == "bearish"
    assert result.opposing_reasons == ["near_support"]
    assert result.invalidation_conditions == [
        "price_not_below_ma20",
        "ma20_not_below_ma50",
        "ma20_slope_non_negative",
        "ma50_slope_non_negative",
        "momentum_turns_bullish",
        "price_breaks_above_20d_high",
    ]


def test_mixed_primary_conflict_has_reassessment_conditions() -> None:
    result = evaluate_market(
        make_context(
            return_5d="-2",
            return_20d="-5",
            rsi14="25",
        )
    )

    assert result.market_view == "mixed"
    assert "trend_momentum_conflict" in result.decision_reasons
    assert result.opposing_reasons == []
    assert result.invalidation_conditions == [
        "momentum_no_longer_opposes_trend",
        "trend_no_longer_opposes_momentum",
    ]


def test_mixed_trend_has_reassessment_conditions() -> None:
    result = evaluate_market(
        make_context(ma50_slope="-0.5")
    )

    assert result.market_view == "mixed"
    assert "trend_not_directional" in result.decision_reasons
    assert result.invalidation_conditions == [
        "trend_becomes_bullish",
        "trend_becomes_bearish",
    ]


def test_level_conflict_has_reassessment_conditions() -> None:
    result = evaluate_market(
        make_context(
            structure=make_structure(recent_low="101"),
        )
    )

    assert result.market_view == "mixed"
    assert result.decision_reasons == [
        "primary_factors_aligned",
        "level_conflicts_with_primary_direction",
    ]
    assert result.invalidation_conditions == [
        "level_no_longer_conflicts_with_primary_direction",
        "primary_direction_changes",
    ]
    level_evidence = evidence_by_metric(result, "level")
    assert level_evidence["current_price_source"].value == "completed_close"
    assert "near_level_atr_threshold" not in level_evidence


def test_breakout_in_primary_direction_is_recorded_as_confirmation() -> None:
    result = evaluate_market(
        make_context(
            current_price="111",
            ma20="105",
            ma50="100",
        )
    )

    assert result.market_view == "bullish"
    assert result.decision_reasons == [
        "primary_factors_aligned",
        "level_confirms_primary_direction",
    ]
    assert result.opposing_reasons == []


def test_decision_contract_requires_trace_and_rejects_it_when_blocked() -> None:
    with pytest.raises(
        ValidationError,
        match="complete/partial decision requires decision_reasons",
    ):
        DecisionResult(
            symbol="NVDA",
            as_of=AS_OF,
            status="complete",
            market_view="bullish",
            rule_version="decision-v1",
        )

    with pytest.raises(
        ValidationError,
        match="blocked decision must not contain directional trace",
    ):
        DecisionResult(
            symbol="NVDA",
            as_of=AS_OF,
            status="blocked",
            rule_version="decision-v1",
            decision_reasons=["trend_momentum_conflict"],
        )
