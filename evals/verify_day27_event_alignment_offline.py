"""Day27 宏观事件与分钟行情时间对齐离线验收。"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.intraday import IntradayBar
from stock_agent.market_reaction.alignment import prepare_event_market_data


EASTERN = ZoneInfo("America/New_York")


def build_release(*, released_at: datetime | None) -> MacroReleaseEvent:
    scheduled_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)
    return MacroReleaseEvent(
        release_id="cpi:2026-09-25",
        release_type="cpi",
        release_date=date(2026, 9, 25),
        scheduled_release_at=scheduled_at,
        released_at=released_at,
        release_date_source="fixture",
        schedule_source="fixture",
        period_binding="verified",
        metrics=[],
    )


def build_bar(start_at: datetime) -> IntradayBar:
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
        session="pre",
    )


def main() -> None:
    event_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)
    as_of = event_at + timedelta(minutes=2)
    bars = [
        build_bar(event_at - timedelta(minutes=2)),
        build_bar(event_at - timedelta(minutes=1)),
        build_bar(event_at),
        build_bar(event_at + timedelta(minutes=1)),
    ]
    provider = FixtureMarketDataProvider(
        quotes={},
        bars={("NVDA", "1m"): bars},
    )

    result = prepare_event_market_data(
        release=build_release(released_at=event_at),
        symbol="NVDA",
        provider=provider,
        as_of=as_of,
    )

    unresolved = prepare_event_market_data(
        release=build_release(released_at=None),
        symbol="NVDA",
        provider=FixtureMarketDataProvider(quotes={}, bars={}),
        as_of=as_of,
    )

    assert result.release_id == "cpi:2026-09-25"
    assert result.symbol == "NVDA"
    assert len(result.pre_bars) == 2
    assert len(result.post_bars) == 2
    assert result.crossing_bar is None
    assert result.status == "ready"
    assert result.issues == []
    assert unresolved.event_at is None
    assert unresolved.status == "unavailable"
    assert unresolved.issues == ["actual_release_time_missing"]

    print("release_id=cpi:2026-09-25")
    print("symbol=NVDA")
    print("pre_bars=2")
    print("post_bars=2")
    print("alignment_status=ready")
    print("missing_actual_time=actual_release_time_missing")
    print("Day27 offline event alignment verification passed.")


if __name__ == "__main__":
    main()
