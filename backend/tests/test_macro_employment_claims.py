from datetime import date, datetime, timezone
from decimal import Decimal
from typing import cast

import pytest

from stock_agent.macro.calculations.claims import calculate_weekly_claims
from stock_agent.macro.calculations.employment import (
    calculate_average_hourly_earnings,
    calculate_nonfarm_payrolls,
    calculate_unemployment_rate,
)
from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.providers.bls import BLSProvider, BLSSeriesPoint
from stock_agent.macro.providers.fred import FredObservation, FredProvider, FredRelease
from stock_agent.macro.providers.fred_claims import (
    CLAIMS_SERIES,
    WeeklyClaimsPoint,
    WeeklyClaimsProvider,
)
from stock_agent.macro.release_builders import (
    EMPLOYMENT_SERIES,
    build_employment_release,
    build_weekly_claims_release,
)


def bls_point(series_id: str, year: int, month: int, value: str) -> BLSSeriesPoint:
    return BLSSeriesPoint(
        series_id=series_id,
        period=date(year, month, 1),
        value=Decimal(value),
    )


def test_employment_calculations_use_comparable_previous_periods():
    payrolls = calculate_nonfarm_payrolls(
        [
            bls_point("payrolls", 2026, 6, "158000"),
            bls_point("payrolls", 2026, 7, "158161"),
            bls_point("payrolls", 2026, 8, "158336.4"),
        ]
    )
    unemployment = calculate_unemployment_rate(
        [
            bls_point("unemployment", 2026, 7, "4.2"),
            bls_point("unemployment", 2026, 8, "4.3"),
        ]
    )
    earnings = calculate_average_hourly_earnings(
        [
            bls_point("earnings", 2025, 7, "34.00"),
            bls_point("earnings", 2025, 8, "34.10"),
            bls_point("earnings", 2026, 6, "35.10"),
            bls_point("earnings", 2026, 7, "35.20"),
            bls_point("earnings", 2026, 8, "35.40"),
        ]
    )

    assert payrolls is not None
    assert payrolls.actual == Decimal("175400.0")
    assert payrolls.previous == Decimal("161000")
    assert unemployment is not None
    assert unemployment.measure == "level"
    assert unemployment.previous == Decimal("4.2")

    by_measure = {metric.measure: metric for metric in earnings}
    assert set(by_measure) == {"level", "mom", "yoy"}
    assert by_measure["mom"].actual == (
        Decimal("35.40") / Decimal("35.20") - 1
    ) * 100
    assert by_measure["yoy"].actual == (
        Decimal("35.40") / Decimal("34.10") - 1
    ) * 100


def test_weekly_claims_previous_requires_exact_prior_week():
    reading = calculate_weekly_claims(
        indicator="initial_claims",
        points=[
            WeeklyClaimsPoint("ICSA", date(2026, 9, 5), 230000),
            WeeklyClaimsPoint("ICSA", date(2026, 9, 19), 225000),
        ],
    )

    assert reading is not None
    assert reading.actual == 225000
    assert reading.previous is None
    assert reading.change is None


class FakeFredObservations:
    def __init__(self, values: list[Decimal]):
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_observations(self, series_id: str, **kwargs):
        self.calls.append({"series_id": series_id, **kwargs})
        return [
            FredObservation(
                series_id=series_id,
                period=date(2026, 9, 12 + index * 7),
                value=value,
            )
            for index, value in enumerate(self.values)
        ]


def test_weekly_claims_provider_uses_as_of_vintage_and_preserves_people():
    fred = FakeFredObservations([Decimal("230000"), Decimal("225000")])
    provider = WeeklyClaimsProvider(cast(FredProvider, fred))

    points = provider.fetch_series(
        "ICSA",
        start_date=date(2026, 8, 1),
        as_of=date(2026, 9, 24),
    )

    assert [point.value for point in points] == [230000, 225000]
    assert fred.calls == [
        {
            "series_id": "ICSA",
            "observation_start": date(2026, 8, 1),
            "observation_end": date(2026, 9, 24),
            "realtime_start": date(2026, 9, 24),
            "realtime_end": date(2026, 9, 24),
        }
    ]


@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("1.5")])
def test_weekly_claims_provider_rejects_invalid_person_counts(value):
    provider = WeeklyClaimsProvider(
        cast(FredProvider, FakeFredObservations([value]))
    )

    with pytest.raises(MacroDataProviderError, match="Invalid claims value"):
        provider.fetch_series(
            "ICSA",
            start_date=date(2026, 8, 1),
            as_of=date(2026, 9, 24),
        )


class FakeReleaseFred:
    def __init__(self, release_date: date):
        self.release_date = release_date

    def get_series_release(self, series_id: str) -> FredRelease:
        return FredRelease(release_id=1, name=series_id)

    def get_release_dates(self, release_id: int, *, include_future: bool):
        return [self.release_date]


class FakeEmploymentBLS:
    def __init__(self, *, mismatched_period: bool = False):
        self.mismatched_period = mismatched_period

    def fetch_series(self, series_ids: list[str]):
        payroll_id = EMPLOYMENT_SERIES["nonfarm_payrolls"]
        unemployment_id = EMPLOYMENT_SERIES["unemployment_rate"]
        earnings_id = EMPLOYMENT_SERIES["average_hourly_earnings"]
        unemployment_month = 7 if self.mismatched_period else 8
        return {
            payroll_id: [
                bls_point(payroll_id, 2026, 6, "158000"),
                bls_point(payroll_id, 2026, 7, "158161"),
                bls_point(payroll_id, 2026, 8, "158336.4"),
            ],
            unemployment_id: [
                bls_point(unemployment_id, 2026, 6, "4.1"),
                bls_point(unemployment_id, 2026, unemployment_month, "4.2"),
            ],
            earnings_id: [
                bls_point(earnings_id, 2025, 7, "34.00"),
                bls_point(earnings_id, 2025, 8, "34.10"),
                bls_point(earnings_id, 2026, 7, "35.20"),
                bls_point(earnings_id, 2026, 8, "35.40"),
            ],
        }


def test_employment_release_groups_metrics_and_detects_period_mismatch():
    warnings: list[str] = []
    release = build_employment_release(
        bls=cast(BLSProvider, FakeEmploymentBLS()),
        fred=cast(FredProvider, FakeReleaseFred(date(2026, 9, 4))),
        consensus=None,
        as_of=datetime(2026, 9, 5, 16, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert release is not None
    assert release.release_type == "employment_situation"
    assert len(release.metrics) == 5
    assert warnings == ["employment_situation_consensus_not_configured"]

    mismatch_warnings: list[str] = []
    mismatched = build_employment_release(
        bls=cast(BLSProvider, FakeEmploymentBLS(mismatched_period=True)),
        fred=cast(FredProvider, FakeReleaseFred(date(2026, 9, 4))),
        consensus=None,
        as_of=datetime(2026, 9, 5, 16, tzinfo=timezone.utc),
        warnings=mismatch_warnings,
    )

    assert mismatched is None
    assert mismatch_warnings == ["employment_period_mismatch"]


class FakeClaims:
    def __init__(self):
        self.calls = 0

    def fetch_series(self, series_id: str, *, start_date: date, as_of: date):
        self.calls += 1
        return [
            WeeklyClaimsPoint(series_id, date(2026, 9, 12), 230000),
            WeeklyClaimsPoint(series_id, date(2026, 9, 19), 225000),
        ]


def test_weekly_claims_release_builds_all_series_after_release_day():
    claims = FakeClaims()
    warnings: list[str] = []

    release = build_weekly_claims_release(
        claims=cast(WeeklyClaimsProvider, claims),
        fred=cast(FredProvider, FakeReleaseFred(date(2026, 9, 24))),
        consensus=None,
        as_of=datetime(2026, 9, 25, 16, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert release is not None
    assert release.release_type == "weekly_claims"
    assert len(release.metrics) == len(CLAIMS_SERIES)
    assert claims.calls == len(CLAIMS_SERIES)
    assert warnings == ["weekly_claims_consensus_not_configured"]


def test_weekly_claims_release_day_does_not_fetch_unverified_actuals():
    claims = FakeClaims()
    warnings: list[str] = []

    release = build_weekly_claims_release(
        claims=cast(WeeklyClaimsProvider, claims),
        fred=cast(FredProvider, FakeReleaseFred(date(2026, 9, 24))),
        consensus=None,
        as_of=datetime(2026, 9, 24, 16, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert release is None
    assert claims.calls == 0
    assert warnings == ["weekly_claims_release_time_unverified"]
