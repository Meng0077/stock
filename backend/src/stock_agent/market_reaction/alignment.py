from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.intraday import (
    HistoricalMinuteBarsRequest,
    IntradayBar,
)
from stock_agent.market.provider import MarketDataProvider
from stock_agent.market_reaction.event_time import resolve_event_time


ONE_MINUTE = timedelta(minutes=1)


def fetch_event_intraday_bars(
    *,
    event_at: datetime,
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
    lookback: timedelta = timedelta(minutes=5),
    lookahead: timedelta = timedelta(hours=2),
) -> tuple[
    HistoricalMinuteBarsRequest,
    list[IntradayBar],
]:
    """获取某次宏观事件前后的已完成分钟行情。

    event_at 是已解析、可用于分钟级研究的实际发布时间。
    此函数不负责验证宏观事件时间来源。
    """

    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("event_at must be timezone-aware")

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if lookback <= timedelta(0):
        raise ValueError("lookback must be positive")
    if lookahead <= timedelta(0):
        raise ValueError("lookahead must be positive")

    event_utc = event_at.astimezone(timezone.utc)
    as_of_utc = as_of.astimezone(timezone.utc)

    if event_utc > as_of_utc:
        raise ValueError("event_at must not be after as_of")

    start_at = (event_utc - lookback).replace(second=0, microsecond=0)

    requested_end = event_utc + lookahead
    end_at = requested_end.replace(second=0, microsecond=0)
    if end_at < requested_end:
        end_at += ONE_MINUTE

    # 不查询 as_of 之后的数据。
    end_at = min(end_at, as_of_utc)

    request = HistoricalMinuteBarsRequest(
        symbol=symbol,
        start_at=start_at,
        end_at=end_at,
        as_of=as_of_utc,
    )

    bars = provider.get_intraday_bars(
        request.symbol,
        start_at=request.start_at,
        end_at=request.end_at,
        as_of=request.as_of,
    )

    return request, bars


def align_event_with_bars(
    *,
    event_at: datetime,
    bars: list[IntradayBar],
) -> tuple[
    list[IntradayBar],
    list[IntradayBar],
    IntradayBar | None,
]:
    """按照实际事件时间划分历史分钟 K 线。

    返回：
        pre_bars：完全位于事件之前的 K 线。
        post_bars：完全位于事件之后的 K 线。
        crossing_bar：跨越事件时间的 K 线，可能不存在。

    假设 bars 已符合 Provider 契约：
    按时间升序、不重复、不重叠。
    """

    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("event_at must be timezone-aware")

    event_utc = event_at.astimezone(timezone.utc)

    pre_bars: list[IntradayBar] = []
    post_bars: list[IntradayBar] = []
    crossing_bar: IntradayBar | None = None

    for bar in bars:
        start = bar.start_at.astimezone(timezone.utc)
        end = bar.end_at.astimezone(timezone.utc)
        if end <= event_utc:
            pre_bars.append(bar)
        elif start >= event_utc:
            post_bars.append(bar)
        else:
            crossing_bar = bar

    return pre_bars, post_bars, crossing_bar


AlignmentStatus = Literal[
    "ready",
    "incomplete",
    "unavailable",
]


def assess_event_alignment(
    *,
    event_at: datetime,
    as_of: datetime,
    pre_bars: list[IntradayBar],
    post_bars: list[IntradayBar],
    crossing_bar: IntradayBar | None,
    max_gap: timedelta = timedelta(minutes=5),
) -> tuple[AlignmentStatus, list[str]]:
    """检查事件附近是否存在可用于后续计算的行情。

    ready 只表示事件前后均有足够接近的完整 K 线，
    不表示事件所在分钟也已观测。issues 可包含非阻断 warning。

    假设 pre_bars、post_bars 已经按照时间升序排列。
    不在这里选取价格或计算收益率。
    """
    event_at = event_at.astimezone(timezone.utc)
    as_of = as_of.astimezone(timezone.utc)

    issues: list[str] = []

    pre_available = False
    if not pre_bars:
        issues.append("pre_bar_missing")
    else:
        pre = pre_bars[-1]
        if event_at - pre.end_at > max_gap:
            issues.append("pre_bar_too_old")
        else:
            pre_available = True

    event_start = event_at.replace(second=0, microsecond=0)

    post_available = False
    if not post_bars:
        post_start = event_start
        if event_at > event_start:
            post_start += timedelta(minutes=1)

        post_end = post_start + timedelta(minutes=1)
        if post_end <= as_of:
            issues.append("post_bar_missing")
        else:
            issues.append("post_bar_not_yet_complete")
    else:
        post = post_bars[0]
        if post.start_at - event_at > max_gap:
            issues.append("post_bar_too_old")
        else:
            post_available = True

    # 事件分钟缺失不阻断后续窗口计算，但不能据此计算第一分钟反应。
    if event_start != event_at and not crossing_bar:
        issues.append("event_minute_not_observed")

    if not pre_available:
        return "unavailable", issues

    if not post_available:
        return "incomplete", issues
    return "ready", issues


@dataclass(slots=True)
class EventMarketAlignment:
    release_id: str
    # release_type: MacroReleaseType
    release_type: str

    symbol: str
    as_of: datetime
    event_at: datetime | None

    pre_bars: list[IntradayBar]
    post_bars: list[IntradayBar]
    crossing_bar: IntradayBar | None

    status: AlignmentStatus
    issues: list[str]


def prepare_timed_event_market_data(
    *,
    event_id: str,
    event_type: str,
    event_at: datetime,
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
    extra_issues: list[str] | None = None,
) -> EventMarketAlignment:
    """
    为一个已经确定实际发生时间的事件准备分钟行情。

    这里不负责判断事件是什么类型，
    也不负责解析事件时间来源。

    调用方必须已经确定：
    - event_id
    - event_type
    - event_at

    本函数只负责：
    - 查询事件附近分钟行情；
    - 按 event_at 切分事件前后 K 线；
    - 判断行情对齐是否可用。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")

    # 获取事件前后的分钟行情。
    _request, bars = fetch_event_intraday_bars(
        event_at=event_at,
        symbol=symbol,
        provider=provider,
        as_of=as_of,
    )

    # 按事件发生时间切分。
    pre, post, crossing = align_event_with_bars(
        event_at=event_at,
        bars=bars,
    )

    status, issues = assess_event_alignment(
        event_at=event_at,
        as_of=as_of,
        pre_bars=pre,
        post_bars=post,
        crossing_bar=crossing,
    )

    if extra_issues:
        issues.extend(extra_issues)

    return EventMarketAlignment(
        release_id=event_id,
        release_type=event_type,
        symbol=symbol,
        as_of=as_of,
        event_at=event_at,
        pre_bars=pre,
        post_bars=post,
        crossing_bar=crossing,
        status=status,
        issues=issues,
    )


def prepare_event_market_data(
    *,
    release: MacroReleaseEvent,
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
) -> EventMarketAlignment:
    """
    为一次宏观发布准备市场行情。

    Macro 层负责解析 released_at；
    真正的行情对齐复用
    prepare_timed_event_market_data()。
    """

    # 解析实际发布时间。
    resolution = resolve_event_time(release=release, as_of=as_of)
    if resolution.event_at is None:
        return EventMarketAlignment(
            release_id=release.release_id,
            release_type=release.release_type,
            symbol=symbol,
            as_of=as_of,
            event_at=None,
            pre_bars=[],
            post_bars=[],
            crossing_bar=None,
            status="unavailable",
            issues=[resolution.reason or "event_time_unavailable"],
        )

    extra_issues = list(resolution.warnings)

    return prepare_timed_event_market_data(
        event_id=release.release_id,
        event_type=release.release_type,
        event_at=resolution.event_at,
        symbol=symbol,
        provider=provider,
        as_of=as_of,
        extra_issues=extra_issues,
    )
