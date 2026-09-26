from datetime import date
from decimal import Decimal
from typing import cast

import httpx

from stock_agent.macro.providers.bea import BEAPCEProvider
from stock_agent.macro.providers.fed import (
    FED_PROJECTION_LONG_RUN,
    FED_PROJECTION_MEDIAN,
    FED_TARGET_LOWER,
    FED_TARGET_UPPER,
    FedDataProvider,
)
from stock_agent.macro.providers.fred import FredObservation, FredProvider
from stock_agent.macro.providers.treasury import TreasuryRatesProvider


def test_bea_provider_parses_pce_series_and_request_parameters():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["UserID"] == "fixture-key"
        assert request.url.params["TableName"] == "T20804"
        assert request.url.params["Year"] == "2025,2026"
        return httpx.Response(
            200,
            json={
                "BEAAPI": {
                    "Results": {
                        "Data": [
                            {
                                "SeriesCode": "DPCERG",
                                "TimePeriod": "2026M7",
                                "DataValue": "125.50",
                            },
                            {
                                "SeriesCode": "DPCCRG",
                                "TimePeriod": "2026M07",
                                "DataValue": "124.20",
                            },
                            {
                                "SeriesCode": "OTHER",
                                "TimePeriod": "2026M7",
                                "DataValue": "999",
                            },
                        ]
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        data = BEAPCEProvider(client, api_key="fixture-key").fetch_indexes(
            years=[2025, 2026]
        )

    assert data["pce"][0].period == date(2026, 7, 1)
    assert data["pce"][0].value == Decimal("125.50")
    assert data["core_pce"][0].value == Decimal("124.20")


class FakeFred:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_observations(self, series_id: str, **kwargs):
        self.calls.append((series_id, kwargs))
        if series_id == FED_TARGET_LOWER:
            return [
                FredObservation(series_id, date(2026, 1, 1), Decimal("4.25")),
                FredObservation(series_id, date(2026, 2, 1), Decimal("4.25")),
                FredObservation(series_id, date(2026, 3, 1), Decimal("4.00")),
            ]
        if series_id == FED_TARGET_UPPER:
            return [
                FredObservation(series_id, date(2026, 1, 1), Decimal("4.50")),
                FredObservation(series_id, date(2026, 2, 1), Decimal("4.50")),
                FredObservation(series_id, date(2026, 3, 1), Decimal("4.25")),
            ]
        if series_id == FED_PROJECTION_MEDIAN:
            return [
                FredObservation(series_id, date(2026, 1, 1), Decimal("3.4")),
                FredObservation(series_id, date(2027, 1, 1), Decimal("3.1")),
            ]
        if series_id == FED_PROJECTION_LONG_RUN:
            return [
                FredObservation(series_id, date(2026, 9, 1), Decimal("3.0"))
            ]
        return [
            FredObservation(series_id, date(2026, 9, 24), Decimal("4.05"))
        ]


def test_fed_provider_collapses_unchanged_ranges_and_reads_sep_vintage():
    fred = FakeFred()
    provider = FedDataProvider(cast(FredProvider, fred))

    ranges = provider.get_target_ranges(as_of=date(2026, 9, 26))
    projections = provider.get_current_projections(as_of=date(2026, 9, 26))

    assert [item.effective_date for item in ranges] == [
        date(2026, 1, 1),
        date(2026, 3, 1),
    ]
    assert [(item.target_year, item.median) for item in projections] == [
        (2026, Decimal("3.4")),
        (2027, Decimal("3.1")),
        ("longer_run", Decimal("3.0")),
    ]
    projection_calls = [
        kwargs
        for series_id, kwargs in fred.calls
        if series_id in {FED_PROJECTION_MEDIAN, FED_PROJECTION_LONG_RUN}
    ]
    assert all(call["realtime_start"] == date(2026, 9, 26) for call in projection_calls)
    assert all(call["realtime_end"] == date(2026, 9, 26) for call in projection_calls)


def test_treasury_provider_maps_each_tenor_and_uses_as_of_vintage():
    fred = FakeFred()
    provider = TreasuryRatesProvider(cast(FredProvider, fred))

    yields = provider.get_yields(
        ["2y", "10y", "2y"],
        as_of=date(2026, 9, 26),
    )

    assert [(item.tenor, item.yield_pct) for item in yields] == [
        ("2y", Decimal("4.05")),
        ("10y", Decimal("4.05")),
    ]
    treasury_calls = fred.calls[-2:]
    assert [series_id for series_id, _ in treasury_calls] == ["DGS2", "DGS10"]
    assert all(
        kwargs["observation_end"] == date(2026, 9, 26)
        and kwargs["realtime_start"] == date(2026, 9, 26)
        and kwargs["realtime_end"] == date(2026, 9, 26)
        for _, kwargs in treasury_calls
    )
