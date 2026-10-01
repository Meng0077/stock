from datetime import datetime, timezone
from decimal import Decimal

import pytest

from stock_agent.decision.engine import DECISION_VERSION, evaluate_market
from stock_agent.decision.models import MarketContext
from stock_agent.market.price_structure import PriceStructureSnapshot
from stock_agent.market.technical import MarketTechnicalSnapshot
from stock_agent.market.volume import VolumeFeatures
from stock_agent.quality.models import DataQualityResult, QualityIssue, QualityStatus
from stock_agent.quality.report import DataQualityReport


AS_OF = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def make_structure(
    *,
    recent_high: str | None = "110",
    recent_low: str | None = "90",
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
        support_candidates=[],
        resistance_candidates=[],
        current_zone=None,
        active_gaps=[],
        fibonacci=None,
    )


def make_technical(
    *,
    current_price: str | None = "100",
    ma20: str | None = "95",
    ma50: str | None = "90",
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
        ma200=None,
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


def make_quality_report(status: QualityStatus) -> DataQualityReport:
    issues = []
    if status != "usable":
        issues = [
            QualityIssue(
                code=f"fixture_{status}",
                message=f"fixture technical quality is {status}",
            )
        ]

    return DataQualityReport(
        as_of=AS_OF,
        results=[
            DataQualityResult(
                data_kind="bars",
                target_id="NVDA",
                purpose="daily_technical",
                status=status,
                issues=issues,
                as_of=AS_OF,
            )
        ],
    )


def make_context(
    technical: MarketTechnicalSnapshot | None,
    *,
    quality_status: QualityStatus | None = "usable",
    requested_components: set[str] | None = None,
    warnings: list[str] | None = None,
) -> MarketContext:
    quality_report = (
        make_quality_report(quality_status)
        if quality_status is not None
        else None
    )
    return MarketContext(
        symbol="NVDA",
        as_of=AS_OF,
        requested_components=requested_components or {"technical"},
        technical=technical,
        quality_report=quality_report,
        warnings=warnings or [],
    )


def test_missing_technical_blocks_before_running_factors() -> None:
    result = evaluate_market(
        make_context(None, quality_status=None, warnings=["provider_failed"])
    )

    assert result.status == "blocked"
    assert result.market_view is None
    assert result.factors == []
    assert result.missing_information == ["technical_missing"]
    assert result.warnings == ["provider_failed"]
    assert result.rule_version == DECISION_VERSION


def test_rejected_technical_quality_preserves_guard_reason() -> None:
    result = evaluate_market(
        make_context(make_technical(), quality_status="rejected")
    )

    assert result.status == "blocked"
    assert result.market_view is None
    assert result.factors == []
    assert result.missing_information == ["technical_quality_rejected"]


@pytest.mark.parametrize(
    ("technical", "expected_view"),
    [
        (make_technical(), "bullish"),
        (
            make_technical(
                current_price="80",
                ma20="90",
                ma50="100",
                ma20_slope="-1",
                ma50_slope="-0.5",
                return_5d="-2",
                return_20d="-5",
                rsi14="25",
                structure=make_structure(recent_low="70"),
            ),
            "bearish",
        ),
    ],
)
def test_complete_decision_requires_all_factors_and_aligned_primary_direction(
    technical: MarketTechnicalSnapshot,
    expected_view: str,
) -> None:
    result = evaluate_market(make_context(technical))

    assert result.status == "complete"
    assert result.market_view == expected_view
    assert [factor.factor for factor in result.factors] == [
        "trend",
        "momentum",
        "level",
    ]
    assert all(factor.status == "usable" for factor in result.factors)
    assert result.missing_information == []
    assert result.decision_reasons == [
        "primary_factors_aligned",
        "level_no_directional_override",
    ]


def test_primary_factor_disagreement_produces_mixed_view() -> None:
    result = evaluate_market(
        make_context(
            make_technical(
                return_5d="-2",
                return_20d="-5",
                rsi14="25",
            )
        )
    )

    assert result.status == "complete"
    assert result.market_view == "mixed"
    assert result.decision_reasons == [
        "trend_momentum_conflict",
        "level_no_directional_override",
    ]


def test_level_breakdown_can_conflict_with_bullish_primary_direction() -> None:
    result = evaluate_market(
        make_context(
            make_technical(
                structure=make_structure(recent_low="101"),
            )
        )
    )

    assert result.status == "complete"
    assert result.market_view == "mixed"
    assert result.factors[2].signal == "bearish"
    assert result.decision_reasons == [
        "primary_factors_aligned",
        "level_conflicts_with_primary_direction",
    ]


def test_degraded_quality_keeps_decision_and_appends_warning() -> None:
    result = evaluate_market(
        make_context(
            make_technical(),
            quality_status="degraded",
            warnings=["source_warning"],
        )
    )

    assert result.status == "complete"
    assert result.market_view == "bullish"
    assert result.warnings == [
        "source_warning",
        "technical_quality_degraded",
    ]


def test_unassessed_quality_is_explicit_but_does_not_block() -> None:
    result = evaluate_market(
        make_context(make_technical(), quality_status=None)
    )

    assert result.status == "complete"
    assert result.market_view == "bullish"
    assert result.warnings == ["technical_quality_not_assessed"]


def test_missing_primary_factor_makes_decision_partial() -> None:
    result = evaluate_market(
        make_context(make_technical(ma50=None))
    )

    assert result.status == "partial"
    assert result.market_view == "bullish"
    assert result.missing_information == ["trend_inputs_missing"]
    assert result.factors[0].status == "insufficient_data"
    assert result.decision_reasons == [
        "momentum_only_available",
        "level_no_directional_override",
    ]


def test_level_can_drive_partial_decision_when_primary_factors_are_unavailable() -> None:
    result = evaluate_market(
        make_context(
            make_technical(
                current_price="111",
                ma20=None,
                return_5d=None,
                structure=make_structure(),
            )
        )
    )

    assert result.status == "partial"
    assert result.market_view == "bullish"
    assert result.missing_information == [
        "trend_inputs_missing",
        "momentum_inputs_missing",
    ]
    assert result.factors[2].signal == "bullish"
    assert result.decision_reasons == ["level_only_available"]


def test_all_unavailable_factors_block_and_remain_in_result() -> None:
    result = evaluate_market(
        make_context(
            make_technical(
                current_price=None,
                ma20=None,
                return_5d=None,
                structure=make_structure(
                    recent_high=None,
                    recent_low=None,
                ),
            )
        )
    )

    assert result.status == "blocked"
    assert result.market_view is None
    assert [factor.status for factor in result.factors] == [
        "insufficient_data",
        "insufficient_data",
        "insufficient_data",
    ]
    assert result.missing_information == [
        "trend_inputs_missing",
        "momentum_inputs_missing",
        "current_price_missing",
    ]


def test_missing_macro_and_market_reaction_do_not_change_technical_decision() -> None:
    context = make_context(
        make_technical(),
        requested_components={"technical", "macro", "market_reaction"},
    )

    result = evaluate_market(context)

    assert context.missing_components == ["macro", "market_reaction"]
    assert result.status == "complete"
    assert result.market_view == "bullish"
    assert result.missing_information == []
