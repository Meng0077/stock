"""Day28 Market Reaction 纯计算引擎离线验收。"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.intraday import IntradayBar
from stock_agent.market.schemas import Bar
from stock_agent.market_reaction.service import research_event_reaction


EASTERN = ZoneInfo("America/New_York")


def build_intraday_bar(
    start_at: datetime,
    close: str,
    session: str,
) -> IntradayBar:
    end_at = start_at + timedelta(minutes=1)
    price = Decimal(close)
    return IntradayBar(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=100,
        is_complete=True,
        adjustment="raw",
        updated_at=end_at,
        received_at=end_at,
        source="fixture",
        data_mode="fixture",
        session=session,
    )


def build_daily_bar(trading_date: date, close: str) -> Bar:
    start_at = datetime(
        trading_date.year,
        trading_date.month,
        trading_date.day,
        9,
        30,
        tzinfo=EASTERN,
    )
    end_at = start_at.replace(hour=16, minute=0)
    price = Decimal(close)
    return Bar(
        symbol="NVDA",
        timeframe="1d",
        start_at=start_at,
        end_at=end_at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1_000,
        is_complete=True,
        adjustment="raw",
        updated_at=end_at,
        received_at=end_at,
        source="fixture",
        data_mode="fixture",
    )


def main() -> None:
    event_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)
    release = MacroReleaseEvent(
        release_id="cpi:2026-09-25",
        release_type="cpi",
        release_date=event_at.date(),
        scheduled_release_at=event_at,
        released_at=event_at,
        release_date_source="fixture",
        schedule_source="fixture",
        period_binding="verified",
        metrics=[],
    )
    intraday = [
        build_intraday_bar(
            event_at - timedelta(minutes=1),
            "100",
            "pre",
        ),
        build_intraday_bar(
            event_at + timedelta(minutes=4),
            "105",
            "pre",
        ),
        build_intraday_bar(
            event_at + timedelta(minutes=29),
            "110",
            "pre",
        ),
        build_intraday_bar(
            event_at + timedelta(minutes=59),
            "120",
            "pre",
        ),
    ]
    provider = FixtureMarketDataProvider(
        quotes={},
        bars={
            ("NVDA", "1m"): intraday,
            ("NVDA", "1d"): [build_daily_bar(event_at.date(), "130")],
        },
    )

    result = research_event_reaction(
        release=release,
        symbol="NVDA",
        provider=provider,
        as_of=event_at.replace(hour=16, minute=1),
    )

    expected_returns = {
        "5m": Decimal("5"),
        "30m": Decimal("10"),
        "1h": Decimal("20"),
        "close": Decimal("30"),
    }
    assert result.reference_price == Decimal("100")
    assert set(result.observations) == set(expected_returns)
    for name, expected_return in expected_returns.items():
        observation = result.observations[name]
        print(
            f"{name}: status={observation.status}, "
            f"return_pct={observation.return_pct}, "
            f"reason={observation.reason}"
        )
        assert observation.status == "usable"
        assert observation.return_pct == expected_return

    print("release_id=", result.release_id)
    print("symbol=", result.symbol)
    print("reference_price=", result.reference_price)
    print("Day28 offline market reaction verification passed.")


if __name__ == "__main__":
    main()
