from datetime import date, datetime, timezone
from decimal import Decimal

from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroRecord,
)
from stock_agent.macro.release_builders import (
    build_longbridge_labor_release,
    build_longbridge_release,
)


RELEASE_DATE = date(2026, 9, 11)
SCHEDULED_AT = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)
AS_OF = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)


class FakeMacro:
    def __init__(self, records):
        self.records = records

    def get_history(
        self,
        indicator,
        measure,
        *,
        start_date,
        end_date,
    ):
        assert start_date == end_date == RELEASE_DATE
        return [self.records[(indicator, measure)]]


def make_record(
    indicator,
    measure,
    unit,
    *,
    period=date(2026, 8, 1),
    actual,
    previous,
    forecast,
):
    return LongbridgeMacroRecord(
        indicator=indicator,
        measure=measure,
        unit=unit,
        period=period,
        actual=Decimal(actual),
        previous=Decimal(previous),
        forecast=(Decimal(forecast) if forecast is not None else None),
        revised=None,
        vendor_release_at=SCHEDULED_AT,
    )


def assert_supplier_forecast(metric, *, estimated_surprise):
    assert metric.consensus_source == "longbridge"
    assert metric.forecast_as_of is None
    assert metric.consensus_pit_verified is False
    assert metric.surprise is None
    assert metric.estimated_surprise == Decimal(estimated_surprise)


def test_inflation_release_uses_supplier_forecast_for_estimated_surprise():
    records = {
        ("cpi", "mom"): make_record(
            "cpi", "mom", "percent",
            actual="0.4", previous="0.1", forecast="0.3",
        ),
        ("cpi", "yoy"): make_record(
            "cpi", "yoy", "percent",
            actual="3.4", previous="3.3", forecast="3.4",
        ),
        ("core_cpi", "mom"): make_record(
            "core_cpi", "mom", "percent",
            actual="0.3", previous="0.2", forecast="0.2",
        ),
        ("core_cpi", "yoy"): make_record(
            "core_cpi", "yoy", "percent",
            actual="2.4", previous="2.5", forecast="2.4",
        ),
    }

    release = build_longbridge_release(
        macro=FakeMacro(records),  # type: ignore[arg-type]
        release_type="cpi",
        release_date=RELEASE_DATE,
        as_of=AS_OF,
        vendor_timezone=timezone.utc,
        warnings=[],
    )

    assert release is not None
    assert_supplier_forecast(
        release.metrics[0],
        estimated_surprise="0.1",
    )


def test_labor_release_uses_supplier_forecast_for_estimated_surprise():
    records = {
        ("nonfarm_payrolls", "monthly_change"): make_record(
            "nonfarm_payrolls", "monthly_change", "jobs",
            actual="100000", previous="90000", forecast="95000",
        ),
        ("unemployment_rate", "level"): make_record(
            "unemployment_rate", "level", "percent",
            actual="4.1", previous="4.0", forecast="4.0",
        ),
        ("average_hourly_earnings", "mom"): make_record(
            "average_hourly_earnings", "mom", "percent",
            actual="0.3", previous="0.2", forecast="0.2",
        ),
    }

    release = build_longbridge_labor_release(
        macro=FakeMacro(records),  # type: ignore[arg-type]
        release_type="employment_situation",
        release_date=RELEASE_DATE,
        as_of=AS_OF,
        vendor_timezone=timezone.utc,
        warnings=[],
    )

    assert release is not None
    assert_supplier_forecast(
        release.metrics[0],
        estimated_surprise="5000",
    )


def test_missing_supplier_forecast_keeps_surprise_fields_empty():
    records = {
        ("cpi", "mom"): make_record(
            "cpi", "mom", "percent",
            actual="0.4", previous="0.1", forecast=None,
        ),
        ("cpi", "yoy"): make_record(
            "cpi", "yoy", "percent",
            actual="3.4", previous="3.3", forecast="3.4",
        ),
        ("core_cpi", "mom"): make_record(
            "core_cpi", "mom", "percent",
            actual="0.3", previous="0.2", forecast="0.2",
        ),
        ("core_cpi", "yoy"): make_record(
            "core_cpi", "yoy", "percent",
            actual="2.4", previous="2.5", forecast="2.4",
        ),
    }

    release = build_longbridge_release(
        macro=FakeMacro(records),  # type: ignore[arg-type]
        release_type="cpi",
        release_date=RELEASE_DATE,
        as_of=AS_OF,
        vendor_timezone=timezone.utc,
        warnings=[],
    )

    assert release is not None
    metric = release.metrics[0]
    assert metric.consensus is None
    assert metric.consensus_source is None
    assert metric.estimated_surprise is None
    assert metric.surprise is None
