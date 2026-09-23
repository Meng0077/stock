from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from longbridge.openapi import Period

from stock_agent.market.schemas import (
    Bar,
    BarTimeframe,
    MarketSession,
    Quote,
    _QuoteCandidate,
)


NEW_YORK = ZoneInfo("America/New_York")


def _normalize_us_timestamp(value: datetime) -> datetime:
    """把 Longbridge 的美股时间统一为 America/New_York。"""

    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(NEW_YORK)


def to_longbridge_symbol(
    symbol: str,
    *,
    region: str = "US",
) -> str:
    """把项目 ticker 转成 Longbridge ticker.region。"""

    normalized_symbol = symbol.strip().upper()
    normalized_region = region.strip().upper()

    if not normalized_symbol:
        raise ValueError("symbol must not be empty")
    if not normalized_region:
        raise ValueError("region must not be empty")

    return f"{normalized_symbol}.{normalized_region}"


def from_longbridge_symbol(longbridge_symbol: str) -> str:
    """把 Longbridge ticker.region 转回项目 ticker。"""

    normalized = longbridge_symbol.strip().upper()
    if "." not in normalized:
        raise ValueError("invalid Longbridge symbol")

    symbol, _region = normalized.rsplit(".", 1)
    if not symbol:
        raise ValueError("invalid Longbridge symbol")

    return symbol


def _build_quote_candidate(
    raw_quote: Any,
    *,
    session: MarketSession,
) -> _QuoteCandidate | None:
    if raw_quote is None:
        return None

    price = getattr(raw_quote, "last_done", None)
    raw_quoted_at = getattr(raw_quote, "timestamp", None)
    if not price or raw_quoted_at is None:
        return None

    return _QuoteCandidate(
        price=Decimal(str(price)),
        quoted_at=_normalize_us_timestamp(raw_quoted_at),
        session=session,
    )


def _select_latest_quote_candidate(
    raw_quote: Any,
) -> _QuoteCandidate | None:
    candidates = [
        candidate
        for candidate in (
            _build_quote_candidate(raw_quote, session="regular"),
            _build_quote_candidate(
                getattr(raw_quote, "pre_market_quote", None),
                session="pre",
            ),
            _build_quote_candidate(
                getattr(raw_quote, "post_market_quote", None),
                session="post",
            ),
            _build_quote_candidate(
                getattr(raw_quote, "overnight_quote", None),
                session="overnight",
            ),
        )
        if candidate is not None
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda candidate: candidate.quoted_at,
    )


def map_longbridge_quote(
    raw_quote: Any,
    *,
    received_at: datetime,
    as_of: datetime,
    is_delayed: bool | None,
) -> Quote | None:
    """把 Longbridge SecurityQuote 转成统一 Quote。"""

    candidate = _select_latest_quote_candidate(raw_quote)
    if candidate is None or candidate.quoted_at > as_of:
        return None

    return Quote(
        symbol=from_longbridge_symbol(raw_quote.symbol),
        price=candidate.price,
        currency="USD",
        quoted_at=candidate.quoted_at,
        received_at=received_at,
        session=candidate.session,
        data_mode="live",
        is_delayed=is_delayed,
        source="longbridge",
    )


def to_longbridge_period(timeframe: BarTimeframe) -> Period:
    """把项目 K 线周期转换成 Longbridge Period。"""

    return {
        "1d": Period.Day,
        "1m": Period.Min_1,
    }[timeframe]


def build_bar_bounds(
    timestamp: datetime,
    *,
    timeframe: BarTimeframe,
) -> tuple[datetime, datetime]:
    """根据 candle 起点构造统一 Bar 时间区间。"""

    start_at = _normalize_us_timestamp(timestamp)
    if timeframe == "1m":
        return start_at, start_at + timedelta(minutes=1)

    trading_date = start_at.date()
    return (
        datetime.combine(
            trading_date,
            time(9, 30),
            tzinfo=NEW_YORK,
        ),
        datetime.combine(
            trading_date,
            time(16, 0),
            tzinfo=NEW_YORK,
        ),
    )


def map_longbridge_bar(
    raw_bar: Any,
    *,
    symbol: str,
    timeframe: BarTimeframe,
    received_at: datetime,
    as_of: datetime,
) -> Bar:
    """把 Longbridge Candlestick 转成统一 Bar。"""

    start_at, end_at = build_bar_bounds(
        raw_bar.timestamp,
        timeframe=timeframe,
    )
    is_complete = end_at <= as_of

    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        start_at=start_at,
        end_at=end_at,
        open=Decimal(str(raw_bar.open)),
        high=Decimal(str(raw_bar.high)),
        low=Decimal(str(raw_bar.low)),
        close=Decimal(str(raw_bar.close)),
        volume=int(raw_bar.volume),
        is_complete=is_complete,
        adjustment="forward_adjusted",
        updated_at=(end_at if is_complete else received_at),
        received_at=received_at,
        source="longbridge",
        data_mode=("historical" if is_complete else "live"),
    )
