from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from stock_agent.market.intraday import IntradayBar

MARKET_REACTION_CALCULATION_VERSION = (
    "market-reaction-v1"
)

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

    # 实际用于这个 observation 的价格来源。
    #
    # 例如：
    # "longbridge"
    # "fixture"
    price_source: str | None = None

    reason: str | None = None

    def __post_init__(self) -> None:
        """保证 observation 状态和结果字段一致。"""
        if self.status == "usable":
            if self.price is None:
                raise ValueError(
                    "usable observation requires price"
                )

            if self.price_at is None:
                raise ValueError(
                    "usable observation requires price_at"
                )

            if self.return_pct is None:
                raise ValueError(
                    "usable observation requires return_pct"
                )

            if self.reason is not None:
                raise ValueError(
                    "usable observation must not contain reason"
                )

            return

        # pending / missing / unavailable
        # 都代表没有可使用的观察结果。
        if self.price is not None:
            raise ValueError(
                "non-usable observation must not contain price"
            )
        if self.price_at is not None:
            raise ValueError(
                "non-usable observation must not contain price_at"
            )

        if self.return_pct is not None:
            raise ValueError(
                "non-usable observation must not contain return_pct"
            )

        if not self.reason:
            raise ValueError(
                "non-usable observation requires reason"
            )


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

    # 实际 reference bar 的行情来源。
    reference_source: str | None = None

    # 实际事件时间的证据来源。
    event_time_source: str | None = None

    calculation_version: str = MARKET_REACTION_CALCULATION_VERSION
