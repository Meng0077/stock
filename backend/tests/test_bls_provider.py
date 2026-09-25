from datetime import date
from decimal import Decimal

import httpx

from stock_agent.macro.calculations.inflation import (
    calculate_inflation_reading,
)
from stock_agent.macro.providers.bls import (
    BLSProvider,
    BLSSeriesPoint,
)


def test_bls_provider_parses_monthly_series():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/publicAPI/v1/timeseries/data/"
        assert request.read() == b'{"seriesid":["CUSR0000SA0"]}'

        return httpx.Response(
            200,
            json={
                "status": "REQUEST_SUCCEEDED",
                "Results": {
                    "series": [
                        {
                            "seriesID": "CUSR0000SA0",
                            "data": [
                                {
                                    "year": "2026",
                                    "period": "M08",
                                    "value": "110.0",
                                },
                                {
                                    "year": "2026",
                                    "period": "M13",
                                    "value": "109.0",
                                },
                                {
                                    "year": "2026",
                                    "period": "M07",
                                    "value": "109.0",
                                },
                            ],
                        }
                    ]
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = BLSProvider(client).fetch_series(["CUSR0000SA0"])

    assert [point.period for point in result["CUSR0000SA0"]] == [
        date(2026, 7, 1),
        date(2026, 8, 1),
    ]
    assert result["CUSR0000SA0"][-1].value == Decimal("110.0")


def test_calculate_inflation_reading_keeps_period_and_rates_separate():
    periods_and_values = [
        (date(2025, 7, 1), "99"),
        (date(2025, 8, 1), "100"),
        (date(2026, 6, 1), "108"),
        (date(2026, 7, 1), "109"),
        (date(2026, 8, 1), "110"),
    ]

    def points(series_id: str) -> list[BLSSeriesPoint]:
        return [
            BLSSeriesPoint(
                series_id=series_id,
                period=period,
                value=Decimal(value),
            )
            for period, value in periods_and_values
        ]

    reading = calculate_inflation_reading(
        sa_points=points("sa"),
        nsa_points=points("nsa"),
    )

    assert reading is not None
    assert reading.period == date(2026, 8, 1)
    assert reading.mom_actual_pct == (
        Decimal("110") / Decimal("109") - 1
    ) * Decimal("100")
    assert reading.yoy_actual_pct == Decimal("10")
    assert reading.mom_previous_pct is not None
    assert reading.yoy_previous_pct is not None
