from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from stock_agent.market.intraday import IntradayBar


def select_reference_bar(
    *,
    event_at: datetime,
    pre_bars: list[IntradayBar],
    max_gap: timedelta = timedelta(minutes=5),
) -> IntradayBar | None:
    """选择事件前最近的完整分钟 K 线。"""

    if not pre_bars:
        return None
    bar = pre_bars[-1]

    if timedelta(0) <= event_at - bar.end_at <= max_gap:
        return bar

    return None


def select_observation_bar(
    *,
    target_at: datetime,
    post_bars: list[IntradayBar],
    as_of: datetime,
    max_lag: timedelta = timedelta(seconds=60),
) -> IntradayBar | None:
    """选择观察时刻之前最近的完整事件后 K 线。"""
    if not post_bars:
        return None
    if target_at > as_of:
        return None

    for bar in reversed(post_bars):
        if bar.end_at > target_at or bar.end_at > as_of:
            continue
        if target_at - bar.end_at < max_lag:
            return bar
        break
    return None

ObservationStatus = Literal[
    "usable",
    "pending",
    "missing",
    "unavailable",
]


@dataclass(frozen=True)
class ObservationResult:
    target_at: datetime

    status: ObservationStatus

    price: Decimal | None = None
    price_at: datetime | None = None
    return_pct: Decimal | None = None

    reason: str | None = None


@dataclass(frozen=True)
class MarketReactionResult:
    release_id: str
    release_type: str
    symbol: str
    event_at: datetime | None

    reference_price: Decimal | None
    reference_at: datetime | None

    observations: dict[str, ObservationResult]
    issues: list[str]
