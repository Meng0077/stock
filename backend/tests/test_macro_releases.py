from datetime import date, datetime, timezone
from decimal import Decimal

from stock_agent.macro.models.metric import (
    ConsensusObservation,
    MacroMetricSnapshot,
)
from stock_agent.macro.providers.fred import FredRelease
from stock_agent.macro.release_builders import (
    build_macro_release,
    get_latest_release_date,
    resolve_scheduled_release_at,
)
from stock_agent.macro.temporal import validate_metric_as_of


def make_metric() -> MacroMetricSnapshot:
    return MacroMetricSnapshot(
        indicator="cpi",
        measure="mom",
        unit="percent",
        period=date(2026, 8, 1),
        actual=Decimal("0.4"),
        release_date=date(2026, 9, 11),
        source="bls",
    )


def test_latest_release_date_excludes_future_dates():
    class FakeFred:
        def get_series_release(self, series_id: str) -> FredRelease:
            assert series_id == "CPIAUCSL"
            return FredRelease(
                release_id=10,
                name="Consumer Price Index",
            )

        def get_release_dates(
            self,
            release_id: int,
            *,
            include_future: bool,
        ) -> list[date]:
            assert release_id == 10
            assert include_future is False
            return [
                date(2026, 8, 12),
                date(2026, 9, 11),
                date(2026, 10, 14),
            ]

    result = get_latest_release_date(
        fred=FakeFred(),  # type: ignore[arg-type]
        series_id="CPIAUCSL",
        as_of=date(2026, 9, 20),
    )

    assert result == date(2026, 9, 11)


def test_build_macro_release_groups_metrics_and_schedule():
    metric = make_metric()
    scheduled_at = datetime(
        2026,
        9,
        11,
        12,
        30,
        tzinfo=timezone.utc,
    )
    forecast = ConsensusObservation(
        indicator="cpi",
        measure="mom",
        period=metric.period,
        scheduled_release_at=scheduled_at,
        consensus=Decimal("0.3"),
        forecast_as_of=None,
        source="fixture",
        event_id="cpi-mom",
    )

    resolved_schedule = resolve_scheduled_release_at(
        metrics=[metric],
        forecasts=[forecast],
    )
    release = build_macro_release(
        release_type="cpi",
        release_date=date(2026, 9, 11),
        metrics=[metric],
        release_date_source="fred",
        scheduled_release_at=resolved_schedule,
        schedule_source="trading_economics",
    )

    assert release.release_id == "cpi:2026-09-11"
    assert release.metrics == [metric]
    assert release.scheduled_release_at == scheduled_at
    assert release.released_at is None
    assert release.period_binding == "latest_assumed"


def test_release_date_rejects_future_metric_without_inventing_time():
    validation = validate_metric_as_of(
        make_metric(),
        as_of=datetime(
            2026,
            9,
            10,
            tzinfo=timezone.utc,
        ),
        strict_pit=False,
    )

    assert validation.decision == "reject"
    assert validation.reason == "release_date_after_as_of"
