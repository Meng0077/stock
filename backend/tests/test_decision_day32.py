from datetime import datetime, timezone
from decimal import Decimal

import pytest

from stock_agent.decision.factors import (
    LEVEL_VERSION,
    MOMENTUM_VERSION,
    TREND_VERSION,
    evaluate_level,
    evaluate_momentum,
    evaluate_trend,
)
from stock_agent.decision.models import MarketContext
from stock_agent.market.indicators import calculate_rsi
from stock_agent.market.price_structure import PriceLevel, PriceStructureSnapshot
from stock_agent.market.technical import MarketTechnicalSnapshot
from stock_agent.market.volume import VolumeFeatures


AS_OF = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def make_level(
    price: str,
    *,
    lower_bound: str | None = None,
    upper_bound: str | None = None,
    atr_distance: str | None = None,
) -> PriceLevel:
    return PriceLevel(
        price=Decimal(price),
        lower_bound=Decimal(lower_bound or price),
        upper_bound=Decimal(upper_bound or price),
        touches=2,
        first_touch_at=AS_OF,
        last_touch_at=AS_OF,
        price_distance=None,
        atr_distance=(
            Decimal(atr_distance) if atr_distance is not None else None
        ),
    )


def make_structure(
    *,
    recent_high: str | None = "110",
    recent_low: str | None = "90",
    support: list[PriceLevel] | None = None,
    resistance: list[PriceLevel] | None = None,
    current_zone: PriceLevel | None = None,
) -> PriceStructureSnapshot:
    return PriceStructureSnapshot(
        recent_high_20d=(
            Decimal(recent_high) if recent_high is not None else None
        ),
        recent_low_20d=(
            Decimal(recent_low) if recent_low is not None else None
        ),
        previous_swing_high=None,
        previous_swing_low=None,
        support_candidates=support or [],
        resistance_candidates=resistance or [],
        current_zone=current_zone,
        active_gaps=[],
        fibonacci=None,
    )


def make_technical(
    *,
    current_price: str | None = "100",
    ma20: str | None = "95",
    ma50: str | None = "90",
    ma200: str | None = None,
    ma20_slope: str | None = "1",
    ma50_slope: str | None = "0.5",
    return_5d: str | None = "2",
    return_20d: str | None = "5",
    rsi14: str | None = "60",
    structure: PriceStructureSnapshot | None = None,
) -> MarketTechnicalSnapshot:
    price = Decimal(current_price) if current_price is not None else None
    return MarketTechnicalSnapshot(
        symbol="NVDA",
        calculation_version="technical-v1",
        input_sources=("fixture",),
        current_price=price,
        price_source="completed_close" if price is not None else None,
        price_at=AS_OF if price is not None else None,
        latest_completed_close=price,
        ma5=None,
        ma20=Decimal(ma20) if ma20 is not None else None,
        ma50=Decimal(ma50) if ma50 is not None else None,
        ma200=Decimal(ma200) if ma200 is not None else None,
        ma20_slope_5d_pct=(
            Decimal(ma20_slope) if ma20_slope is not None else None
        ),
        ma50_slope_5d_pct=(
            Decimal(ma50_slope) if ma50_slope is not None else None
        ),
        return_5d_pct=(
            Decimal(return_5d) if return_5d is not None else None
        ),
        return_20d_pct=(
            Decimal(return_20d) if return_20d is not None else None
        ),
        rsi14=Decimal(rsi14) if rsi14 is not None else None,
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


def make_context(
    technical: MarketTechnicalSnapshot | None,
) -> MarketContext:
    return MarketContext(
        symbol="NVDA",
        as_of=AS_OF,
        requested_components={"technical"},
        technical=technical,
    )


def test_rsi_uses_wilder_smoothing_and_handles_boundary_series() -> None:
    assert calculate_rsi(
        [Decimal(value) for value in ("1", "2", "1", "3", "2")],
        period=2,
    ) == Decimal("50")
    assert calculate_rsi([Decimal("1")] * 15) == Decimal("50")
    assert calculate_rsi([Decimal(value) for value in range(1, 16)]) == Decimal(
        "100"
    )
    assert calculate_rsi([Decimal(value) for value in range(15, 0, -1)]) == Decimal(
        "0"
    )
    assert calculate_rsi([Decimal("1")] * 14) is None


@pytest.mark.parametrize(
    ("price", "ma20", "ma50", "ma20_slope", "ma50_slope", "signal"),
    [
        ("110", "105", "100", "1", "0.5", "bullish"),
        ("90", "95", "100", "-1", "-0.5", "bearish"),
        ("110", "105", "100", "1", "-0.5", "mixed"),
    ],
)
def test_trend_requires_aligned_price_ma_and_slope_structure(
    price: str,
    ma20: str,
    ma50: str,
    ma20_slope: str,
    ma50_slope: str,
    signal: str,
) -> None:
    result = evaluate_trend(
        make_context(
            make_technical(
                current_price=price,
                ma20=ma20,
                ma50=ma50,
                ma20_slope=ma20_slope,
                ma50_slope=ma50_slope,
            )
        )
    )

    assert result.status == "usable"
    assert result.signal == signal
    assert result.rule_version == TREND_VERSION


def test_trend_records_ma200_without_using_it_as_a_required_input() -> None:
    result = evaluate_trend(
        make_context(make_technical(current_price="110", ma200="120"))
    )

    assert result.signal == "bullish"
    assert "price_below_ma200" in result.reasons
    assert {item.metric for item in result.evidence} == {
        "current_price",
        "ma20",
        "ma50",
        "ma20_slope_5d_pct",
        "ma50_slope_5d_pct",
        "ma200",
    }


@pytest.mark.parametrize(
    ("return_5d", "return_20d", "rsi14", "signal", "rsi_reason"),
    [
        ("2", "5", "75", "bullish", "rsi_overbought"),
        ("-2", "-5", "25", "bearish", "rsi_oversold"),
        ("0", "0", "50", "neutral", "rsi_neutral"),
        ("2", "-5", "45", "mixed", "rsi_weak"),
    ],
)
def test_momentum_uses_returns_for_direction_and_rsi_for_state(
    return_5d: str,
    return_20d: str,
    rsi14: str,
    signal: str,
    rsi_reason: str,
) -> None:
    result = evaluate_momentum(
        make_context(
            make_technical(
                return_5d=return_5d,
                return_20d=return_20d,
                rsi14=rsi14,
            )
        )
    )

    assert result.status == "usable"
    assert result.signal == signal
    assert rsi_reason in result.reasons
    assert result.rule_version == MOMENTUM_VERSION
    assert [item.metric for item in result.evidence] == [
        "return_5d_pct",
        "return_20d_pct",
        "rsi14",
    ]


@pytest.mark.parametrize(
    ("price", "signal", "reason"),
    [
        ("111", "bullish", "breakout_above_20d_high"),
        ("89", "bearish", "breakdown_below_20d_low"),
    ],
)
def test_level_detects_20_day_breakout_and_breakdown(
    price: str,
    signal: str,
    reason: str,
) -> None:
    result = evaluate_level(make_context(make_technical(current_price=price)))

    assert result.status == "usable"
    assert result.signal == signal
    assert result.reasons == [reason]
    assert result.rule_version == LEVEL_VERSION


def test_level_marks_current_pivot_zone_as_mixed() -> None:
    structure = make_structure(
        current_zone=make_level(
            "100",
            lower_bound="99",
            upper_bound="101",
            atr_distance="0",
        )
    )

    result = evaluate_level(
        make_context(make_technical(structure=structure))
    )

    assert result.signal == "mixed"
    assert result.reasons == ["at_key_price_zone"]
    assert {item.metric for item in result.evidence} >= {
        "current_zone_lower_bound",
        "current_zone_upper_bound",
    }


@pytest.mark.parametrize(
    ("support_distance", "resistance_distance", "signal", "reasons"),
    [
        ("0.5", "0.4", "mixed", ["near_support", "near_resistance", "inside_tight_range"]),
        ("0.5", "0.8", "neutral", ["near_support"]),
        ("0.8", "0.5", "neutral", ["near_resistance"]),
        ("0.8", "0.9", "neutral", ["not_near_key_level"]),
    ],
)
def test_level_uses_half_atr_proximity_threshold(
    support_distance: str,
    resistance_distance: str,
    signal: str,
    reasons: list[str],
) -> None:
    structure = make_structure(
        support=[make_level("98", atr_distance=support_distance)],
        resistance=[make_level("102", atr_distance=resistance_distance)],
    )

    result = evaluate_level(
        make_context(make_technical(structure=structure))
    )

    assert result.signal == signal
    assert result.reasons == reasons


@pytest.mark.parametrize(
    ("evaluator", "factor", "version"),
    [
        (evaluate_trend, "trend", TREND_VERSION),
        (evaluate_momentum, "momentum", MOMENTUM_VERSION),
        (evaluate_level, "level", LEVEL_VERSION),
    ],
)
def test_factors_report_missing_technical_without_a_signal(
    evaluator,
    factor: str,
    version: str,
) -> None:
    result = evaluator(make_context(None))

    assert result.factor == factor
    assert result.status == "insufficient_data"
    assert result.signal is None
    assert result.reasons == ["technical_missing"]
    assert result.rule_version == version


def test_factors_report_missing_required_inputs() -> None:
    trend = evaluate_trend(make_context(make_technical(ma50=None)))
    momentum = evaluate_momentum(make_context(make_technical(rsi14=None)))
    level = evaluate_level(
        make_context(
            make_technical(
                structure=make_structure(
                    recent_high=None,
                    recent_low=None,
                )
            )
        )
    )

    assert trend.reasons == ["trend_inputs_missing"]
    assert momentum.reasons == ["momentum_inputs_missing"]
    assert level.reasons == ["level_data_missing"]
    assert {trend.status, momentum.status, level.status} == {
        "insufficient_data"
    }
