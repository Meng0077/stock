from datetime import date, datetime, timezone
from decimal import Decimal
from typing import cast

from stock_agent.macro.models.metric import ConsensusObservation
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
            tzinfo=timezone.utc,
        ),
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
