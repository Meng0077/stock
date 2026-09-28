from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.intraday import IntradayBar
from stock_agent.market.schemas import Bar
from stock_agent.market_reaction.alignment import EventMarketAlignment
from stock_agent.market_reaction.calculator import (
    calculate_close_observation,
    calculate_market_reaction,
)
from stock_agent.market_reaction.service import research_event_reaction
from stock_agent.market_reaction.trading_calendar import resolve_close_at


EASTERN = ZoneInfo("America/New_York")


def make_intraday_bar(
    start_at: datetime,
    close: str,
    *,
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


def make_daily_bar(trading_date: date, close: str) -> Bar:
    start_at = datetime.combine(
        trading_date,
        datetime.min.time(),
        tzinfo=EASTERN,
    ).replace(hour=9, minute=30)
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


def make_release(event_at: datetime) -> MacroReleaseEvent:
    return MacroReleaseEvent(
        release_id=f"cpi:{event_at.date().isoformat()}",
        release_type="cpi",
        release_date=event_at.date(),
        scheduled_release_at=event_at,
        released_at=event_at,
        release_date_source="fixture",
        schedule_source="fixture",
        period_binding="verified",
        metrics=[],
    )


def test_minute_windows_use_wall_clock_time_across_sessions() -> None:
    event_at = datetime(2026, 9, 25, 9, 15, 20, tzinfo=EASTERN)
    reference = make_intraday_bar(
        event_at.replace(minute=14, second=0),
        "100",
        session="pre",
    )
    bars = [
        make_intraday_bar(
            event_at.replace(minute=19, second=0),
            "105",
            session="pre",
        ),
        make_intraday_bar(
            event_at.replace(minute=44, second=0),
            "110",
            session="regular",
        ),
        make_intraday_bar(
            event_at.replace(hour=10, minute=14, second=0),
            "120",
            session="regular",
        ),
    ]
    alignment = EventMarketAlignment(
        release_id="cpi:2026-09-25",
        release_type="cpi",
        symbol="NVDA",
        as_of=event_at.replace(hour=10, minute=16),
        event_at=event_at,
        pre_bars=[reference],
        post_bars=bars,
        crossing_bar=None,
        status="ready",
        issues=["event_minute_not_observed"],
    )

    result = calculate_market_reaction(alignment)

    assert result.reference_price == Decimal("100")
    assert result.observations["5m"].return_pct == Decimal("5.00")
    assert result.observations["30m"].return_pct == Decimal("10.0")
    assert result.observations["1h"].return_pct == Decimal("20.0")
    assert result.observations["5m"].price_at == bars[0].end_at
    assert result.observations["30m"].price_at == bars[1].end_at
    assert result.observations["1h"].price_at == bars[2].end_at


def test_minute_windows_distinguish_pending_and_missing() -> None:
    event_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)
    reference = make_intraday_bar(
        event_at - timedelta(minutes=1),
        "100",
        session="pre",
    )
    alignment = EventMarketAlignment(
        release_id="cpi:2026-09-25",
        release_type="cpi",
        symbol="NVDA",
        as_of=event_at + timedelta(minutes=10),
        event_at=event_at,
        pre_bars=[reference],
        post_bars=[],
        crossing_bar=None,
        status="incomplete",
        issues=[],
    )

    pending = calculate_market_reaction(alignment)
    assert pending.observations["5m"].status == "missing"
    assert pending.observations["30m"].status == "pending"
    assert pending.observations["1h"].status == "pending"

    alignment.as_of = event_at + timedelta(hours=2)
    missing = calculate_market_reaction(alignment)
    assert all(
        observation.status == "missing"
        for observation in missing.observations.values()
    )


def test_after_hours_event_uses_next_trading_session_close() -> None:
    event_at = datetime(2026, 9, 25, 17, 0, tzinfo=EASTERN)

    close_at, session_date = resolve_close_at(event_at)

    assert close_at == datetime(2026, 9, 28, 16, 0, tzinfo=EASTERN)
    assert session_date == "2026-09-28"


def test_close_observation_rejects_adjustment_mismatch() -> None:
    close_at = datetime(2026, 9, 25, 16, 0, tzinfo=EASTERN)
    daily_bar = make_daily_bar(close_at.date(), "130")
    daily_bar = daily_bar.model_copy(
        update={"adjustment": "forward_adjusted"}
    )

    result = calculate_close_observation(
        close_at=close_at,
        as_of=close_at + timedelta(minutes=1),
        reference_price=Decimal("100"),
        reference_adjustment="raw",
        daily_bar=daily_bar,
    )

    assert result.status == "unavailable"
    assert result.reason == "price_adjustment_mismatch"


def test_service_returns_minute_windows_and_official_close() -> None:
    event_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)
    intraday = [
        make_intraday_bar(
            event_at - timedelta(minutes=1),
            "100",
            session="pre",
        ),
        make_intraday_bar(
            event_at + timedelta(minutes=4),
            "105",
            session="pre",
        ),
        make_intraday_bar(
            event_at + timedelta(minutes=29),
            "110",
            session="pre",
        ),
        make_intraday_bar(
            event_at + timedelta(minutes=59),
            "120",
            session="pre",
        ),
    ]
    daily = make_daily_bar(event_at.date(), "130")
    provider = FixtureMarketDataProvider(
        quotes={},
        bars={
            ("NVDA", "1m"): intraday,
            ("NVDA", "1d"): [daily],
        },
    )

    result = research_event_reaction(
        release=make_release(event_at),
        symbol="NVDA",
        provider=provider,
        as_of=event_at.replace(hour=16, minute=1),
    )

    assert result.reference_price == Decimal("100")
    assert result.observations["5m"].return_pct == Decimal("5.00")
    assert result.observations["30m"].return_pct == Decimal("10.0")
    assert result.observations["1h"].return_pct == Decimal("20.0")
    assert result.observations["close"].return_pct == Decimal("30.0")
    assert all(
        observation.status == "usable"
        for observation in result.observations.values()
    )
