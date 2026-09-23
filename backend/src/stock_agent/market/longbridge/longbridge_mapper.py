from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from longbridge.openapi import Period

from stock_agent.market.schemas import (
    MarketSession,
    Quote,
    BarTimeframe,
    Bar
)

from stock_agent.market.schemas import _QuoteCandidate





def to_longbridge_symbol(
    symbol: str,
    *,
    region: str = "US",
) -> str:
    """把系统内部 ticker 转成 Longbridge symbol。

    Args:
        symbol:
            系统内部证券代码，例如：
            "NVDA"、"AAPL"、"BRK.B"。

        region:
            Longbridge 市场后缀。
            Day22 第一版只实际使用 "US"。

    Returns:
        Longbridge 使用的 ticker.region 格式，
        例如：
            "NVDA.US"
            "BRK.B.US"

    不负责：
        - 公司名称解析；
        - 判断 ticker 是否真实存在；
        - 查询市场信息。
    """
    normalized_symbol = symbol.strip().upper()
    normalized_region = region.strip().upper()
    if not normalized_symbol:
        raise ValueError("region must not be empty")

    return f"{normalized_symbol}.{normalized_region}"


def from_longbridge_symbol(
    longbridge_symbol: str,
) -> str:
    """把 Longbridge symbol 转回系统内部 ticker。

    Args:
        longbridge_symbol:
            Longbridge 的 ticker.region，
            例如 "NVDA.US"、"BRK.B.US"。

    Returns:
        系统内部 ticker，
        例如 "NVDA"、"BRK.B"。

    Raises:
        ValueError:
            输入不包含市场后缀。
    """

    normalized= longbridge_symbol.strip().upper()
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
    """把 Longbridge 的某一个交易时段行情转换成候选值。

    Args:
        raw_quote:
            Longbridge quote 对象或扩展时段 quote 对象。

        session:
            该对象属于哪个交易时段。

    Returns:
        有有效价格和时间时返回候选值；
        数据缺失时返回 None。

    本函数只做字段转换，
    不决定最终应该选择哪个 session。
    """

    if raw_quote is None:
        return None

    price = getattr(raw_quote, "last_done", None)
    quoted_at= getattr(raw_quote, 'timestamp', None)
    if not price or not quoted_at:
        return None

    if (
        quoted_at.tzinfo is None
        or quoted_at.utcoffset() is None
    ):
        raise ValueError(
            "Longbridge quote timestamp "
            "must be timezone-aware"
        )

    return _QuoteCandidate(
        price=Decimal(str(price)),
        quoted_at=quoted_at,
        session=session,
    )


def _select_latest_quote_candidate(
    raw_quote: Any,
) -> _QuoteCandidate | None:
    """从 regular / pre / post / overnight 中选择最新报价。

    Args:
        raw_quote:
            Longbridge SecurityQuote。

    Returns:
        timestamp 最新的候选行情。
        没有有效价格时返回 None。

    Longbridge pull quote 同时可能保存多个交易阶段的数据，
    因此不能无条件只使用顶层 last_done。
    """
    candidates: list[_QuoteCandidate] = []
    regular = _build_quote_candidate(raw_quote, session="regular")
    if regular is not None:
        candidates.append(regular)

    pre_market = _build_quote_candidate(getattr( raw_quote, "pre_market_quote", None,), session="pre")
    if pre_market is not None:
        candidates.append(pre_market)

    post_market = _build_quote_candidate(getattr( raw_quote, "post_market_quote", None,), session="post")
    if post_market is not None:
        candidates.append(post_market)

    overnight = _build_quote_candidate(getattr( raw_quote, "overnight_quote", None,), session="overnight")
    if overnight is not None:
        candidates.append(overnight)

    return max(candidates, key=lambda candidate: candidate.quoted_at)


def map_longbridge_quote(
    raw_quote: Any,
    *,
    received_at: datetime,
    as_of: datetime,
    is_delayed: bool | None,
) -> Quote | None:
    """把 Longbridge SecurityQuote 转成项目统一 Quote。

    Args:
        raw_quote:
            Longbridge SDK 返回的一条 SecurityQuote。

        received_at:
            我们系统真正收到 API 响应的时间。

        as_of:
            本次研究允许使用的最大市场信息时间。

        is_delayed:
            Provider 已知的行情延迟状态。

            mapper 不负责推断行情权限，
            只负责记录 Provider 告诉它的结果。

    Returns:
        转换后的 Quote。

        如果：
            - 没有有效行情；
            - 最新市场行情晚于 as_of；

        返回 None。

    不负责：
        - 网络请求；
        - API 认证；
        - retry；
        - 公司名称解析。
    """
    candidate = _select_latest_quote_candidate(raw_quote)
    # PIT 约束看市场时间，而不是系统响应时间。
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

def to_longbridge_period(
    timeframe: BarTimeframe,
) -> Period:
    """把项目内部 timeframe 转成 Longbridge Period。

    Args:
        timeframe:
            项目统一 K 线周期，例如 "1d"、"1m"。

    Returns:
        Longbridge SDK 对应的 Period。

    Raises:
        ValueError:
            当前 Longbridge Provider 尚未支持该周期。

    本函数属于供应商 Adapter 层，
    Longbridge 的 Period 不应该暴露给 Agent 上层。
    """

    mapping = {
        "1d": Period.Day,
        "1m": Period.Min_1,
    }

    period = mapping.get(timeframe)

    if period is None:
        raise ValueError(
            f"unsupported timeframe: {timeframe}"
        )

    return period

NEW_YORK = ZoneInfo(
    "America/New_York"
)


TIMEFRAME_DURATIONS = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
}

def build_intraday_bar_bounds(timestamp: datetime, *, timeframe: BarTimeframe,)-> tuple[datetime, datetime]:
    duration = TIMEFRAME_DURATIONS.get(timeframe)
    return (timestamp, timestamp + duration)

def build_daily_bar_bounds(timestamp: datetime) -> tuple[datetime, datetime]:
    trading_date = timestamp.astimezone(NEW_YORK).date()
    return(
        datetime.combine(trading_date, time(9, 30), tzinfo=NEW_YORK),
        datetime.combine(trading_date, time(16, 0), tzinfo=NEW_YORK),
    )

def build_bar_bounds(
    timestamp: datetime,
    *,
    timeframe: BarTimeframe,
) -> tuple[datetime, datetime]:
    """根据 Longbridge candle timestamp 构造统一 Bar 时间区间。

    Args:
        timestamp:
            Longbridge Candlestick.timestamp。

        timeframe:
            项目内部周期。

    Returns:
        (start_at, end_at)

    规则：
        1d:
            第一版按美股普通 regular session：
            09:30 -> 16:00 America/New_York。

        1m:
            timestamp -> timestamp + 1 minute。

    Raises:
        ValueError:
            timestamp 没有时区；
            或当前 timeframe 尚不支持。

    注意：
        Daily 的提前收盘日暂未处理，
        交易日历属于 Day25。
    """

    if (
        timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise ValueError(
            "candlestick timestamp "
            "must be timezone-aware"
        )

    if timeframe in TIMEFRAME_DURATIONS:
        return build_intraday_bar_bounds(timestamp, timeframe=timeframe)

    if timeframe == "1d":
        return build_daily_bar_bounds(timestamp)

    raise ValueError(
        f"unsupported timeframe: {timeframe}"
    )


def map_longbridge_bar(
    raw_bar: Any,
    *,
    symbol: str,
    timeframe: BarTimeframe,
    received_at: datetime,
    as_of: datetime,
) -> Bar:
    """把一根 Longbridge Candlestick 转成统一 Bar。
    rgs:
        raw_bar:
            Longbridge SDK 返回的 Candlestick。

        symbol:
            项目内部 ticker，例如 "NVDA"。

        timeframe:
            项目统一周期。

        received_at:
            本系统收到这批行情响应的时间。

        as_of:
            本次研究使用的市场参考时间。

    Returns:
        项目统一 Bar。

    规则：
        end_at <= as_of
            → completed historical Bar。

        end_at > as_of
            → 当前仍在形成的 Bar。

    注意：
        Longbridge 当前 Candlestick 没有提供一个能够直接
        等同于我们 updated_at 的可靠字段，
        因此 updated_at 保持 None。

        不使用 received_at 冒充市场更新时间。
    """

    start_at, end_at = build_bar_bounds(raw_bar.timestamp, timeframe=timeframe)
    is_complete = end_at <= as_of

    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        start_at=start_at,
        end_at=end_at,
        # Provider 没有可靠的 Bar 市场更新时间，
        # 不人为伪造。
        updated_at=None,
        # 表示我们的系统什么时候收到该数据。
        received_at=received_at,
        open=Decimal(str(raw_bar.open)),
        high=Decimal(str(raw_bar.high)),
        low=Decimal(str(raw_bar.low)),
        close=Decimal(str(raw_bar.close)),
        volume=int(raw_bar.volume),
        is_complete=is_complete,
        adjustment="forward_adjusted",
        source="longbridge",
        data_mode=(
            "historical"
            if is_complete
            else "live"
        ),
    )
