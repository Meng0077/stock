from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from stock_agent.market.errors import MarketDataCapabilityError, MarketDataProviderError
from stock_agent.market.provider import MarketDataProvider
from stock_agent.market.schemas import Bar
from stock_agent.market_reaction.alignment import EventMarketAlignment
from stock_agent.market_reaction.calculator import calculate_close_observation
from stock_agent.market_reaction.models import (
    ObservationResult,
    select_reference_bar,
)
from stock_agent.market_reaction.trading_calendar import resolve_close_at


NEW_YORK = ZoneInfo("America/New_York")


def get_target_daily_bar(
    *,
    provider: MarketDataProvider,
    symbol: str,
    close_at: datetime,
    as_of: datetime,
) -> Bar | None:
    """获取指定历史交易日已完成的原始日线。"""

    # 目标交易日还没有收盘。
    if as_of < close_at:
        return None

    target_date = close_at.astimezone(NEW_YORK).date()

    # 定位到目标收盘日附近，而不是研究截止日附近。
    # 不能超过用户传入的 as_of。
    query_as_of = min(
        as_of,
        close_at + timedelta(days=1),
    )

    bars = provider.get_bars(
        symbol=symbol,
        as_of=query_as_of,
        timeframe="1d",
        limit=5,
        include_incomplete=False,
        adjustment="raw",
    )

    for bar in bars:
        bar_date = bar.start_at.astimezone(NEW_YORK).date()

        # 必须属于正确的交易日。
        # Mapper 已将日线结束时间映射成
        # 交易所日历中的实际收盘时间。
        if bar_date != target_date or bar.end_at != close_at:
            continue

        if (
            not bar.is_complete
            or bar.adjustment != "raw"
            or (bar.updated_at is not None and bar.updated_at > as_of)
        ):
            continue

        return bar
    return None


def build_close_observation(
    *,
    alignment: EventMarketAlignment,
    provider: MarketDataProvider,
) -> ObservationResult | None:
    """取得目标日线并计算正式收盘收益率。"""

    if alignment.event_at is None:
        return None

    close_at, _ = resolve_close_at(alignment.event_at)

    reference_bar = select_reference_bar(
        event_at=alignment.event_at,
        pre_bars=alignment.pre_bars,
    )
    if reference_bar is None:
        return ObservationResult(
            target_at=close_at,
            status="unavailable",
            reason="reference_bar_unavailable",
        )

    # 避免在收盘前发起无意义的日线查询。
    daily_bar = None
    if alignment.as_of >= close_at:
        try:
            daily_bar = get_target_daily_bar(
                provider=provider,
                symbol=alignment.symbol,
                close_at=close_at,
                as_of=alignment.as_of,
            )
        except MarketDataCapabilityError:
            return ObservationResult(
                target_at=close_at,
                status="unavailable",
                reason="daily_data_capability_unavailable",
            )
        except MarketDataProviderError:
            return ObservationResult(
                target_at=close_at,
                status="unavailable",
                reason="daily_data_provider_error",
            )

    return calculate_close_observation(
        close_at=close_at,
        as_of=alignment.as_of,
        reference_price=reference_bar.close,
        reference_adjustment=reference_bar.adjustment,
        daily_bar=daily_bar,
    )
