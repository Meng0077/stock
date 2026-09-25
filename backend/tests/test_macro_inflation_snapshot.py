from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.calculations.inflation import (
    InflationReading,
    build_inflation_metrics,
)
from stock_agent.macro.models.metric import (
    ConsensusObservation,
    EconomicMeasure,
)


EASTERN = ZoneInfo("America/New_York")
PERIOD = date(2026, 8, 1)
RELEASE_DATE = date(2026, 9, 11)
RELEASED_AT = datetime(2026, 9, 11, 8, 30, tzinfo=EASTERN)


def make_reading() -> InflationReading:
    return InflationReading(
        period=PERIOD,
        mom_actual_pct=Decimal("0.396"),
        mom_previous_pct=Decimal("0.074"),
        yoy_actual_pct=Decimal("3.397"),
        yoy_previous_pct=Decimal("3.365"),
    )


def make_forecast(
    *,
    measure: EconomicMeasure,
    consensus: str,
    forecast_as_of: datetime | None,
) -> ConsensusObservation:
    return ConsensusObservation(
        indicator="cpi",
        measure=measure,
        period=PERIOD,
        scheduled_release_at=RELEASED_AT,
        consensus=Decimal(consensus),
        forecast_as_of=forecast_as_of,
        source="fixture",
        event_id=f"cpi-{measure}",
    )


def test_build_inflation_metrics_keeps_date_and_time_separate():
    metrics = build_inflation_metrics(
        indicator="cpi",
        reading=make_reading(),
        forecasts=[],
        release_date=RELEASE_DATE,
    )

    assert set(metrics) == {"mom", "yoy"}
    assert metrics["mom"].period == PERIOD
    assert metrics["mom"].release_date == RELEASE_DATE
    assert metrics["mom"].released_at is None
    assert metrics["yoy"].release_date == RELEASE_DATE
    assert metrics["mom"].actual_pit_status == "unverified"
    assert metrics["mom"].source == "bls"
    assert metrics["mom"].surprise_is_estimated is True


def test_missing_release_date_does_not_invent_release_time():
    metrics = build_inflation_metrics(
        indicator="cpi",
        reading=make_reading(),
        forecasts=[],
        release_date=None,
    )

    assert metrics["mom"].release_date is None
    assert metrics["mom"].released_at is None


def test_unverified_consensus_never_produces_surprise():
    forecast = make_forecast(
        measure="mom",
        consensus="0.3",
        forecast_as_of=None,
    )

    metric = build_inflation_metrics(
        indicator="cpi",
        reading=make_reading(),
        forecasts=[forecast],
        release_date=RELEASE_DATE,
    )["mom"]

    assert metric.consensus == Decimal("0.3")
    assert metric.consensus_pit_verified is False
    assert metric.surprise is None


def test_verified_pre_release_consensus_produces_rounded_surprise():
    forecast = make_forecast(
        measure="mom",
        consensus="0.3",
        forecast_as_of=datetime(
            2026,
            9,
            10,
            12,
            tzinfo=EASTERN,
        ),
    )

    metric = build_inflation_metrics(
        indicator="cpi",
        reading=make_reading(),
        forecasts=[forecast],
        release_date=RELEASE_DATE,
        released_at=RELEASED_AT,
    )["mom"]

    assert metric.consensus_pit_verified is True
    assert metric.surprise == Decimal("0.1")
