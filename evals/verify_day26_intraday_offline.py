"""Day26 历史分钟行情离线验收。"""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.market.errors import MarketDataCapabilityError
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.intraday import HistoricalMinuteBarsRequest, IntradayBar
from stock_agent.quality.intraday import validate_intraday_bars


NEW_YORK = ZoneInfo("America/New_York")


def build_bar(start_at: datetime, session: str) -> IntradayBar:
    end_at = start_at + timedelta(minutes=1)
    return IntradayBar(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        open=Decimal("180"),
        high=Decimal("181"),
        low=Decimal("179"),
        close=Decimal("180.5"),
        volume=100,
        is_complete=True,
        adjustment="raw",
        updated_at=end_at,
        received_at=end_at,
        source="fixture",
        data_mode="fixture",
        session=session,
    )


def main() -> None:
    trading_date = datetime(2026, 9, 25, tzinfo=NEW_YORK)
    start_at = trading_date.replace(hour=8)
    end_at = trading_date.replace(hour=16, minute=1)
    as_of = trading_date.replace(hour=17)
    bars = [
        build_bar(start_at, "pre"),
        build_bar(trading_date.replace(hour=9, minute=30), "regular"),
        build_bar(trading_date.replace(hour=16), "post"),
    ]
    request = HistoricalMinuteBarsRequest(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        as_of=as_of,
    )

    provider = FixtureMarketDataProvider(
        quotes={},
        bars={("NVDA", "1m"): bars},
    )
    result = provider.get_intraday_bars(
        "NVDA",
        start_at=start_at,
        end_at=end_at,
        as_of=as_of,
    )
    quality = validate_intraday_bars(
        request=request,
        bars=result,
        required_sessions=["pre", "regular", "post"],
    )

    assert len(result) == 3
    assert quality.status == "usable"

    try:
        FixtureMarketDataProvider(
            quotes={},
            bars={},
        ).get_intraday_bars(
            "NVDA",
            start_at=start_at,
            end_at=end_at,
            as_of=as_of,
        )
    except MarketDataCapabilityError as exc:
        capability_error = exc
    else:
        raise AssertionError("missing minute capability must be explicit")

    print("bars=", len(result))
    print("quality_status=", quality.status)
    print("capability_error=", type(capability_error).__name__)
    print("Day26 offline intraday verification passed.")


if __name__ == "__main__":
    main()
