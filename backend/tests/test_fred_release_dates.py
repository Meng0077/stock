from datetime import date

import httpx

from stock_agent.macro.providers.fred import FredProvider


def test_fred_provider_gets_series_release_and_dates():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/series/release"):
            assert request.url.params["series_id"] == "CPIAUCSL"
            return httpx.Response(
                200,
                json={
                    "releases": [
                        {
                            "id": 10,
                            "name": "Consumer Price Index",
                        }
                    ]
                },
            )

        assert request.url.path.endswith("/release/dates")
        assert request.url.params["release_id"] == "10"
        assert (
            request.url.params[
                "include_release_dates_with_no_data"
            ]
            == "false"
        )
        return httpx.Response(
            200,
            json={
                "release_dates": [
                    {"date": "2026-09-11"},
                    {"date": "2026-08-12"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = FredProvider(client, api_key="fixture")
        release = provider.get_series_release("CPIAUCSL")
        dates = provider.get_release_dates(release.release_id)

    assert release.release_id == 10
    assert release.name == "Consumer Price Index"
    assert dates == [
        date(2026, 8, 12),
        date(2026, 9, 11),
    ]
