from datetime import date, datetime, timezone
from decimal import Decimal

from stock_agent.macro.forecast_capture import (
    ForecastQuote,
    ForecastSnapshot,
    append_forecast_snapshot,
    capture_next_forecasts,
)
from stock_agent.macro.forecast_matching import (
    load_forecast_snapshots,
    match_release_forecasts,
)
from stock_agent.macro.models.metric import MacroMetricSnapshot
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroRecord,
)


PERIOD = date(2026, 9, 1)
RELEASE_DATE = date(2026, 10, 14)
SCHEDULED_AT = datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
CAPTURED_AT = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def make_record(
    indicator,
    measure,
    unit,
    forecast,
) -> LongbridgeMacroRecord:
    return LongbridgeMacroRecord(
        indicator=indicator,
        measure=measure,
        unit=unit,
        period=PERIOD,
        actual=None,
        previous=None,
        forecast=Decimal(forecast),
        revised=None,
        vendor_release_at=SCHEDULED_AT,
    )


class FakeMacro:
    records = {
        ("cpi", "mom"): make_record(
            "cpi", "mom", "percent", "0.3"
        ),
        ("cpi", "yoy"): make_record(
            "cpi", "yoy", "percent", "2.8"
        ),
        ("core_cpi", "mom"): make_record(
            "core_cpi", "mom", "percent", "0.2"
        ),
        ("core_cpi", "yoy"): make_record(
            "core_cpi", "yoy", "percent", "3.0"
        ),
    }

    def get_history(
        self,
        indicator,
        measure,
        *,
        start_date,
        end_date,
    ):
        return [self.records[(indicator, measure)]]


def make_snapshot(*, captured_at: datetime = CAPTURED_AT):
    return ForecastSnapshot(
        release_type="cpi",
        release_date=RELEASE_DATE,
        scheduled_release_at=SCHEDULED_AT,
        captured_at=captured_at,
        forecasts=(
            ForecastQuote(
                indicator="cpi",
                measure="mom",
                unit="percent",
                period=PERIOD,
                consensus=Decimal("0.3"),
            ),
        ),
    )


def test_capture_next_forecasts_collects_one_release():
    warnings = []

    snapshot = capture_next_forecasts(
        macro=FakeMacro(),  # type: ignore[arg-type]
        release_type="cpi",
        vendor_timezone=timezone.utc,
        warnings=warnings,
        clock=lambda: CAPTURED_AT,
    )

    assert snapshot is not None
    assert snapshot.release_date == RELEASE_DATE
    assert snapshot.captured_at == CAPTURED_AT
    assert len(snapshot.forecasts) == 4
    assert warnings == []


def test_forecast_snapshot_round_trip(tmp_path):
    path = tmp_path / "macro_forecasts.jsonl"
    snapshot = make_snapshot()

    append_forecast_snapshot(snapshot, path)

    assert load_forecast_snapshots(path) == [snapshot]


def test_saved_forecast_produces_estimated_surprise():
    release = MacroReleaseEvent(
        release_id="cpi:2026-10-14",
        release_type="cpi",
        release_date=RELEASE_DATE,
        scheduled_release_at=SCHEDULED_AT,
        released_at=None,
        release_date_source="longbridge",
        schedule_source="longbridge",
        period_binding="latest_assumed",
        metrics=[
            MacroMetricSnapshot(
                indicator="cpi",
                measure="mom",
                unit="percent",
                period=PERIOD,
                actual=Decimal("0.4"),
                release_date=RELEASE_DATE,
                source="longbridge",
                actual_pit_status="unverified",
            )
        ],
    )

    updated, comparisons, warnings = match_release_forecasts(
        release=release,
        snapshots=[make_snapshot()],
        as_of=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
    )

    metric = updated.metrics[0]
    assert metric.consensus == Decimal("0.3")
    assert metric.consensus_source == "longbridge"
    assert metric.forecast_as_of == CAPTURED_AT
    assert metric.estimated_surprise == Decimal("0.1")
    assert metric.surprise is None
    assert metric.consensus_pit_verified is False
    assert comparisons[0].full_pit_verified is False
    assert warnings == []


def test_unrelated_snapshot_does_not_add_missing_forecast_warning():
    release = MacroReleaseEvent(
        release_id="cpi:2026-10-13",
        release_type="cpi",
        release_date=date(2026, 10, 13),
        release_date_source="longbridge",
        period_binding="latest_assumed",
        metrics=[
            MacroMetricSnapshot(
                indicator="cpi",
                measure="mom",
                unit="percent",
                period=PERIOD,
                actual=Decimal("0.4"),
                release_date=date(2026, 10, 13),
                source="longbridge",
            )
        ],
    )

    updated, comparisons, warnings = match_release_forecasts(
        release=release,
        snapshots=[make_snapshot()],
        as_of=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
    )

    assert updated == release
    assert comparisons == []
    assert warnings == []
