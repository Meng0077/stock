from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.calculations.consensus import (
    find_release_consensus,
    merge_consensus,
)
from stock_agent.macro.models.metric import (
    ConsensusObservation,
    MacroMetricSnapshot,
)


EASTERN = ZoneInfo("America/New_York")
PERIOD = date(2026, 8, 1)
RELEASE_DATE = date(2026, 9, 4)
RELEASED_AT = datetime(2026, 9, 4, 8, 30, tzinfo=EASTERN)


def make_forecast(
    *,
    value: str,
    forecast_as_of: datetime | None,
    event_id: str,
    period: date = PERIOD,
) -> ConsensusObservation:
    return ConsensusObservation(
        indicator="nonfarm_payrolls",
        measure="monthly_change",
        period=period,
        scheduled_release_at=RELEASED_AT,
        consensus=Decimal(value),
        forecast_as_of=forecast_as_of,
        source="fixture",
        event_id=event_id,
    )


def make_metric(*, actual_pit_status: str = "unverified") -> MacroMetricSnapshot:
    return MacroMetricSnapshot(
        indicator="nonfarm_payrolls",
        measure="monthly_change",
        unit="jobs",
        period=PERIOD,
        actual=Decimal("175400"),
        previous=Decimal("161000"),
        release_date=RELEASE_DATE,
        released_at=RELEASED_AT,
        source="bls",
        actual_pit_status=actual_pit_status,
    )


def test_consensus_uses_latest_unique_verified_pre_release_forecast():
    older = make_forecast(
        value="170000",
        forecast_as_of=datetime(2026, 9, 2, 12, tzinfo=EASTERN),
        event_id="older",
    )
    latest = make_forecast(
        value="175000",
        forecast_as_of=datetime(2026, 9, 3, 12, tzinfo=EASTERN),
        event_id="latest",
    )
    after_release = make_forecast(
        value="180000",
        forecast_as_of=datetime(2026, 9, 4, 9, tzinfo=EASTERN),
        event_id="after",
    )

    match = find_release_consensus(
        forecasts=[older, after_release, latest],
        indicator="nonfarm_payrolls",
        measure="monthly_change",
        period=PERIOD,
        release_date=RELEASE_DATE,
        released_at=RELEASED_AT,
    )

    assert match is not None
    assert match.forecast.event_id == "latest"
    assert match.pit_verified is True


def test_consensus_requires_exact_period_and_release_date():
    wrong_period = make_forecast(
        value="175000",
        forecast_as_of=None,
        event_id="wrong-period",
        period=date(2026, 7, 1),
    )

    match = find_release_consensus(
        forecasts=[wrong_period],
        indicator="nonfarm_payrolls",
        measure="monthly_change",
        period=PERIOD,
        release_date=RELEASE_DATE,
        released_at=None,
    )

    assert match is None


def test_ambiguous_unverified_forecasts_are_not_selected():
    forecasts = [
        make_forecast(value="170000", forecast_as_of=None, event_id="a"),
        make_forecast(value="175000", forecast_as_of=None, event_id="b"),
    ]

    match = find_release_consensus(
        forecasts=forecasts,
        indicator="nonfarm_payrolls",
        measure="monthly_change",
        period=PERIOD,
        release_date=RELEASE_DATE,
        released_at=None,
    )

    assert match is None


def test_unverified_consensus_is_kept_without_surprise():
    metric = make_metric()
    forecast = make_forecast(
        value="175000",
        forecast_as_of=None,
        event_id="calendar",
    )

    result = merge_consensus(metrics=[metric], forecasts=[forecast])[0]

    assert result.consensus == Decimal("175000")
    assert result.consensus_pit_verified is False
    assert result.surprise is None
    assert result.surprise_is_estimated is False
    assert metric.consensus is None


def test_verified_consensus_calculates_surprise_with_actual_quality_flag():
    metric = make_metric()
    forecast = make_forecast(
        value="175000",
        forecast_as_of=datetime(2026, 9, 3, 12, tzinfo=EASTERN),
        event_id="verified",
    )

    result = merge_consensus(metrics=[metric], forecasts=[forecast])[0]

    assert result.consensus == Decimal("175000")
    assert result.surprise == Decimal("400")
    assert result.consensus_pit_verified is True
    assert result.surprise_is_estimated is True
