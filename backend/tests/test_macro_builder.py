from datetime import date, datetime, timezone
from decimal import Decimal
from typing import cast

from stock_agent.macro.models.metric import ConsensusObservation
from stock_agent.macro.providers.bea import BEAIndexPoint, BEAPCEProvider
from stock_agent.macro.providers.bls import (
    BLSProvider,
    BLSSeriesPoint,
)
from stock_agent.macro.providers.fred import (
    FredProvider,
    FredRelease,
)
from stock_agent.macro.providers.trading_economics import (
    TradingEconomicsConsensusProvider,
)
from stock_agent.macro.release_builders import (
    INFLATION_SERIES,
    build_bls_inflation_release,
    build_pce_release,
)


RELEASE_DATE = date(2026, 9, 11)
RELEASE_AT = datetime(
    2026,
    9,
    11,
    12,
    30,
    tzinfo=timezone.utc,
)


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
        return [RELEASE_DATE]


class FakeBLS:
    def fetch_series(
        self,
        series_ids: list[str],
    ) -> dict[str, list[BLSSeriesPoint]]:
        periods_and_values = [
            (date(2025, 7, 1), Decimal("99")),
            (date(2025, 8, 1), Decimal("100")),
            (date(2026, 6, 1), Decimal("108")),
            (date(2026, 7, 1), Decimal("109")),
            (date(2026, 8, 1), Decimal("110")),
        ]

        return {
            series_id: [
                BLSSeriesPoint(
                    series_id=series_id,
                    period=period,
                    value=value,
                )
                for period, value in periods_and_values
            ]
            for series_id in series_ids
        }


class FakeConsensus:
    def get_consensus(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[ConsensusObservation]:
        assert start_date == end_date == RELEASE_DATE

        return [
            ConsensusObservation(
                indicator=indicator,
                measure=measure,
                period=date(2026, 8, 1),
                scheduled_release_at=RELEASE_AT,
                consensus=Decimal(value),
                forecast_as_of=None,
                source="fixture",
                event_id=f"{indicator}-{measure}",
            )
            for indicator in ("cpi", "core_cpi")
            for measure, value in (
                ("mom", "0.3"),
                ("yoy", "3.3"),
            )
        ]


def test_builder_builds_cpi_release_from_fred_bls_and_consensus():
    warnings: list[str] = []
    release = build_bls_inflation_release(
        bls=cast(BLSProvider, FakeBLS()),
        consensus=cast(
            TradingEconomicsConsensusProvider,
            FakeConsensus(),
        ),
        fred=cast(FredProvider, FakeFred()),
        release_type="cpi",
        as_of=datetime(
            2026,
            9,
            12,
            12,
            tzinfo=timezone.utc,
        ),
        warnings=warnings,
    )

    assert release is not None
    assert release.release_id == "cpi:2026-09-11"
    assert release.release_date_source == "fred"
    assert release.scheduled_release_at == RELEASE_AT
    assert release.released_at is None
    assert release.period_binding == "latest_assumed"
    assert len(release.metrics) == 4
    assert {
        (metric.indicator, metric.measure)
        for metric in release.metrics
    } == {
        ("cpi", "mom"),
        ("cpi", "yoy"),
        ("core_cpi", "mom"),
        ("core_cpi", "yoy"),
    }
    assert all(
        metric.release_date == RELEASE_DATE
        for metric in release.metrics
    )
    assert set(INFLATION_SERIES) >= {"cpi", "core_cpi"}
    assert warnings == []


def test_builder_keeps_actuals_when_consensus_is_not_configured():
    warnings: list[str] = []

    release = build_bls_inflation_release(
        bls=cast(BLSProvider, FakeBLS()),
        consensus=None,
        fred=cast(FredProvider, FakeFred()),
        release_type="cpi",
        as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert release is not None
    assert len(release.metrics) == 4
    assert all(metric.consensus is None for metric in release.metrics)
    assert all(metric.surprise is None for metric in release.metrics)
    assert warnings == ["cpi_consensus_not_configured"]


def test_builder_does_not_fetch_actuals_on_date_only_release_day():
    class FailingBLS:
        def fetch_series(self, series_ids: list[str]):
            raise AssertionError("actual data must not be fetched")

    warnings: list[str] = []
    release = build_bls_inflation_release(
        bls=cast(BLSProvider, FailingBLS()),
        consensus=None,
        fred=cast(FredProvider, FakeFred()),
        release_type="cpi",
        as_of=datetime(2026, 9, 11, 20, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert release is None
    assert warnings == ["cpi_release_time_unverified"]


def test_builder_builds_pce_release_from_bea_and_fred():
    class FakePCEFred:
        def get_series_release(self, series_id: str) -> FredRelease:
            assert series_id == "PCEPI"
            return FredRelease(release_id=54, name="Personal Income and Outlays")

        def get_release_dates(self, release_id: int, *, include_future: bool):
            return [date(2026, 9, 25)]

    class FakeBEA:
        def fetch_indexes(self, *, years: list[int]):
            assert years == [2024, 2025, 2026]
            periods_and_values = [
                (date(2025, 7, 1), Decimal("99")),
                (date(2025, 8, 1), Decimal("100")),
                (date(2026, 6, 1), Decimal("108")),
                (date(2026, 7, 1), Decimal("109")),
                (date(2026, 8, 1), Decimal("110")),
            ]
            return {
                indicator: [
                    BEAIndexPoint(
                        series_code=series_code,
                        period=period,
                        value=value,
                    )
                    for period, value in periods_and_values
                ]
                for indicator, series_code in (
                    ("pce", "DPCERG"),
                    ("core_pce", "DPCCRG"),
                )
            }

    warnings: list[str] = []
    release = build_pce_release(
        bea=cast(BEAPCEProvider, FakeBEA()),
        consensus=None,
        fred=cast(FredProvider, FakePCEFred()),
        as_of=datetime(2026, 9, 26, 16, tzinfo=timezone.utc),
        warnings=warnings,
    )

    assert release is not None
    assert release.release_type == "pce"
    assert len(release.metrics) == 4
    assert {metric.indicator for metric in release.metrics} == {
        "pce",
        "core_pce",
    }
    assert all(metric.source == "bea" for metric in release.metrics)
    assert warnings == ["pce_consensus_not_configured"]
