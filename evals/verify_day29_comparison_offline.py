"""Day29 多标的基准比较与历史事件筛选离线验收。"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market_reaction.comparison import compare_market_reactions
from stock_agent.market_reaction.history import select_historical_releases
from stock_agent.market_reaction.models import (
    MarketReactionResult,
    ObservationResult,
)
from stock_agent.market_reaction.multi_symbol import normalize_symbols


EASTERN = ZoneInfo("America/New_York")
WINDOWS = ("5m", "30m", "1h", "close")


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


def make_reaction(
    *,
    release: MacroReleaseEvent,
    symbol: str,
    returns: tuple[str, str, str, str],
) -> MarketReactionResult:
    event_at = release.released_at
    assert event_at is not None
    offsets = (
        timedelta(minutes=5),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=7, minutes=30),
    )
    observations = {
        window: ObservationResult(
            target_at=event_at + offset,
            status="usable",
            price=Decimal("100") * (
                Decimal("1") + Decimal(return_pct) / Decimal("100")
            ),
            price_at=event_at + offset,
            return_pct=Decimal(return_pct),
        )
        for window, offset, return_pct in zip(WINDOWS, offsets, returns)
    }
    return MarketReactionResult(
        release_id=release.release_id,
        release_type=release.release_type,
        symbol=symbol,
        event_at=event_at,
        reference_price=Decimal("100"),
        reference_at=event_at - timedelta(minutes=1),
        observations=observations,
        issues=[],
    )


def main() -> None:
    recent = make_release(date(2026, 9, 25))
    older = make_release(date(2026, 8, 12))
    nvda = make_reaction(
        release=recent,
        symbol="NVDA",
        returns=("5", "10", "20", "30"),
    )
    qqq = make_reaction(
        release=recent,
        symbol="QQQ",
        returns=("2", "5", "15", "25"),
    )

    comparison = compare_market_reactions(lhs=nvda, rhs=qqq)
    differences = {
        window: observation.difference_pp
        for window, observation in comparison.observations.items()
    }
    assert differences == {
        "5m": Decimal("3"),
        "30m": Decimal("5"),
        "1h": Decimal("5"),
        "close": Decimal("5"),
    }
    assert normalize_symbols(["nvda", "QQQ", "soxx", "NVDA"]) == (
        "NVDA",
        "QQQ",
        "SOXX",
    )

    as_of = datetime(2026, 9, 29, 12, tzinfo=EASTERN)
    selected = select_historical_releases(
        [older, recent],
        release_type="cpi",
        before=as_of,
        as_of=as_of,
        limit=2,
    )
    assert [release.release_id for release in selected] == [
        recent.release_id,
        older.release_id,
    ]

    print("symbols=NVDA,QQQ,SOXX")
    print("difference_pp=", differences)
    print("historical_releases=", [release.release_id for release in selected])
    print("Day29 offline comparison verification passed.")


if __name__ == "__main__":
    main()
