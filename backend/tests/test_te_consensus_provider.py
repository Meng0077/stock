from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from stock_agent.macro.providers.trading_economics import (
    TradingEconomicsConsensusProvider,
)


def test_te_consensus_provider_sends_key_and_parses_cpi_forecast():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["c"] == "fixture-key"
        return httpx.Response(
            200,
            json=[
                {
                    "CalendarId": "cpi-mom",
                    "Country": "United States",
                    "Event": "Inflation Rate MoM",
                    "DateSpan": "0",
                    "Forecast": "0.3%",
                    "ReferenceDate": "2026-08-01T00:00:00",
                    "Date": "2026-09-11T12:30:00Z",
                },
                {
                    "CalendarId": "missing-forecast",
                    "Country": "United States",
                    "Event": "Inflation Rate YoY",
                    "DateSpan": "0",
                    "Forecast": "",
                    "ReferenceDate": "2026-08-01T00:00:00",
                    "Date": "2026-09-11T12:30:00Z",
                },
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = TradingEconomicsConsensusProvider(
            client,
            api_key="fixture-key",
        )
        observations = provider.get_consensus(
            start_date=date(2026, 9, 11),
            end_date=date(2026, 9, 11),
        )

    assert len(observations) == 1
    assert observations[0].indicator == "cpi"
    assert observations[0].measure == "mom"
    assert observations[0].period == date(2026, 8, 1)
    assert observations[0].consensus == Decimal("0.3")
    assert observations[0].scheduled_release_at == datetime(
        2026,
        9,
        11,
        12,
        30,
        tzinfo=timezone.utc,
    )
    assert observations[0].forecast_as_of is None
