from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.intraday import IntradayBar
from stock_agent.market.schemas import Bar
from stock_agent.market_reaction.comparison import (
    compare_event_symbols,
    compare_market_reactions,
    compare_observations,
)
from stock_agent.market_reaction.history import select_historical_releases
from stock_agent.market_reaction.history_service import (
    research_historical_multi_symbol_reactions,
)
from stock_agent.market_reaction.models import ObservationResult
from stock_agent.market_reaction.multi_symbol import (
    normalize_symbols,
    research_multi_symbol_event_reaction,
)


EASTERN = ZoneInfo("America/New_York")


def make_release(day: date) -> MacroReleaseEvent:
    event_at = datetime(day.year, day.month, day.day, 8, 30, tzinfo=EASTERN)
    return MacroReleaseEvent(
        release_id=f"cpi:{day.isoformat()}",
        release_type="cpi",
        release_date=day,
        scheduled_release_at=event_at,
        released_at=event_at,
        release_date_source="fixture",
        schedule_source="fixture",
        period_binding="verified",
        metrics=[],
    )


def make_intraday_bar(
    *,
    symbol: str,
    start_at: datetime,
    close: str,
) -> IntradayBar:
    end_at = start_at + timedelta(minutes=1)
    price = Decimal(close)
    return IntradayBar(
        symbol=symbol,
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
        session="pre",
    )


def make_daily_bar(*, symbol: str, day: date, close: str) -> Bar:
    start_at = datetime(day.year, day.month, day.day, 9, 30, tzinfo=EASTERN)
    end_at = start_at.replace(hour=16, minute=0)
    price = Decimal(close)
    return Bar(
        symbol=symbol,
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


def add_reaction_bars(
    bars: dict[tuple[str, str], list[Bar]],
    *,
    release: MacroReleaseEvent,
    symbol: str,
    prices: tuple[str, str, str, str, str],
) -> None:
    event_at = release.released_at
    assert event_at is not None
    reference, at_5m, at_30m, at_1h, at_close = prices
    bars.setdefault((symbol, "1m"), []).extend(
        [
            make_intraday_bar(
                symbol=symbol,
                start_at=event_at - timedelta(minutes=1),
                close=reference,
            ),
            make_intraday_bar(
                symbol=symbol,
                start_at=event_at + timedelta(minutes=4),
                close=at_5m,
            ),
            make_intraday_bar(
                symbol=symbol,
                start_at=event_at + timedelta(minutes=29),
                close=at_30m,
            ),
            make_intraday_bar(
                symbol=symbol,
                start_at=event_at + timedelta(minutes=59),
                close=at_1h,
            ),
        ]
    )
    bars.setdefault((symbol, "1d"), []).append(
        make_daily_bar(symbol=symbol, day=release.release_date, close=at_close)
    )


def test_multi_symbol_reaction_and_benchmark_difference() -> None:
    release = make_release(date(2026, 9, 25))
    bars: dict[tuple[str, str], list[Bar]] = {}
    add_reaction_bars(
        bars,
        release=release,
        symbol="NVDA",
        prices=("100", "105", "110", "120", "130"),
    )
    add_reaction_bars(
        bars,
        release=release,
        symbol="QQQ",
        prices=("100", "102", "105", "115", "125"),
    )
    add_reaction_bars(
        bars,
        release=release,
        symbol="SOXX",
        prices=("100", "101", "104", "112", "120"),
    )
    provider = FixtureMarketDataProvider(quotes={}, bars=bars)

    result = research_multi_symbol_event_reaction(
        release=release,
        symbols=["nvda", "QQQ", "soxx", "NVDA"],
        provider=provider,
        as_of=datetime(2026, 9, 25, 16, 1, tzinfo=EASTERN),
    )
    comparison = compare_event_symbols(
        event=result,
        lhs_symbol="NVDA",
        rhs_symbol="QQQ",
    )

    assert result.symbols == ("NVDA", "QQQ", "SOXX")
    assert set(comparison.observations) == {"5m", "30m", "1h", "close"}
    assert {
        window: observation.difference_pp
        for window, observation in comparison.observations.items()
    } == {
        "5m": Decimal("3.00"),
        "30m": Decimal("5.00"),
        "1h": Decimal("5.00"),
        "close": Decimal("5.00"),
    }
    assert all(
        observation.status == "usable"
        for observation in comparison.observations.values()
    )

    with pytest.raises(ValueError, match="releases do not match"):
        compare_market_reactions(
            lhs=result.reactions["NVDA"],
            rhs=replace(result.reactions["QQQ"], release_id="other"),
        )
    with pytest.raises(ValueError, match="event times do not match"):
        compare_market_reactions(
            lhs=result.reactions["NVDA"],
            rhs=replace(
                result.reactions["QQQ"],
                event_at=result.event_at + timedelta(seconds=1),
            ),
        )


def test_comparison_uses_worse_status_and_requires_both_returns() -> None:
    target_at = datetime(2026, 9, 25, 8, 35, tzinfo=EASTERN)
    lhs = ObservationResult(
        target_at=target_at,
        status="usable",
        return_pct=Decimal("5"),
    )
    rhs = ObservationResult(
        target_at=target_at,
        status="pending",
        reason="target_not_reached",
    )

    result = compare_observations(lhs, rhs)

    assert result.status == "pending"
    assert result.difference_pp is None
    assert result.lhs_return_pct == Decimal("5")
    assert result.rhs_return_pct is None
    assert result.rhs_reason == "target_not_reached"

    with pytest.raises(ValueError, match="target times do not match"):
        compare_observations(
            lhs,
            replace(rhs, target_at=target_at + timedelta(minutes=1)),
        )


def test_normalize_symbols_rejects_blank_symbol() -> None:
    with pytest.raises(ValueError, match="symbol must not be empty"):
        normalize_symbols(["NVDA", "   "])


class FailingQqqProvider(FixtureMarketDataProvider):
    def get_intraday_bars(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        as_of: datetime,
    ) -> list[IntradayBar]:
        if symbol == "QQQ":
            raise MarketDataProviderError("fixture failure")
        return super().get_intraday_bars(
            symbol,
            start_at=start_at,
            end_at=end_at,
            as_of=as_of,
        )


def test_one_provider_failure_does_not_hide_other_symbols() -> None:
    release = make_release(date(2026, 9, 25))
    bars: dict[tuple[str, str], list[Bar]] = {}
    add_reaction_bars(
        bars,
        release=release,
        symbol="NVDA",
        prices=("100", "105", "110", "120", "130"),
    )
    provider = FailingQqqProvider(quotes={}, bars=bars)

    result = research_multi_symbol_event_reaction(
        release=release,
        symbols=["NVDA", "QQQ"],
        provider=provider,
        as_of=datetime(2026, 9, 25, 16, 1, tzinfo=EASTERN),
    )

    assert result.reactions["NVDA"].observations["5m"].status == "usable"
    assert result.reactions["QQQ"].observations == {}
    assert result.reactions["QQQ"].issues == ["minute_data_provider_error"]


def test_historical_query_returns_recent_same_type_reactions() -> None:
    recent = make_release(date(2026, 9, 25))
    older = make_release(date(2026, 8, 12))
    oldest = make_release(date(2026, 7, 14))
    bars: dict[tuple[str, str], list[Bar]] = {}
    for release in (recent, older, oldest):
        for symbol in ("NVDA", "QQQ"):
            add_reaction_bars(
                bars,
                release=release,
                symbol=symbol,
                prices=("100", "101", "102", "103", "104"),
            )
    provider = FixtureMarketDataProvider(quotes={}, bars=bars)
    as_of = datetime(2026, 9, 29, 12, tzinfo=EASTERN)

    result = research_historical_multi_symbol_reactions(
        releases=[oldest, older, recent],
        release_type="cpi",
        symbols=["nvda", "qqq"],
        before=as_of,
        limit=2,
        provider=provider,
        as_of=as_of,
    )

    assert result.symbols == ("NVDA", "QQQ")
    assert [event.release_id for event in result.events] == [
        recent.release_id,
        older.release_id,
    ]
    assert all(
        event.reactions["NVDA"].observations["5m"].status == "usable"
        for event in result.events
    )


def test_historical_selection_requires_matching_type_and_exact_past_time() -> None:
    as_of = datetime(2026, 9, 29, 12, tzinfo=EASTERN)
    eligible = make_release(date(2026, 9, 25))
    missing_time = make_release(date(2026, 8, 12)).model_copy(
        update={"released_at": None}
    )
    other_type = make_release(date(2026, 9, 24)).model_copy(
        update={
            "release_id": "ppi:2026-09-24",
            "release_type": "ppi",
        }
    )
    at_before = make_release(date(2026, 9, 29)).model_copy(
        update={
            "release_id": "cpi:at-before",
            "released_at": as_of,
        }
    )
    after_as_of = make_release(date(2026, 9, 30))

    selected = select_historical_releases(
        [missing_time, other_type, at_before, after_as_of, eligible],
        release_type="cpi",
        before=as_of,
        as_of=as_of,
        limit=5,
    )

    assert selected == [eligible]
