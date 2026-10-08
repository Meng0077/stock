from dataclasses import replace
from datetime import datetime

from stock_agent.macro.models.release import (
    MacroReleaseEvent,
)
from stock_agent.market.errors import MarketDataCapabilityError, MarketDataProviderError
from stock_agent.market.provider import MarketDataProvider
from stock_agent.market_reaction.alignment import (
    prepare_timed_event_market_data,
)
from stock_agent.market_reaction.calculator import (
    calculate_market_reaction,
)
from stock_agent.market_reaction.close_data import (
    build_close_observation,
)
from stock_agent.market_reaction.event_time import resolve_event_time
from stock_agent.market_reaction.models import MarketReactionResult


def _timed_event_failure_result(
    *,
    event_id: str,
    event_type: str,
    event_at: datetime,
    event_time_source: str | None,
    symbol: str,
    reason: str,
    extra_issues: list[str] | None = None,
) -> MarketReactionResult:
    """分钟行情不可用时返回结构化事件反应结果。"""

    issues = [reason]

    if extra_issues:
        issues.extend(extra_issues)

    return MarketReactionResult(
        release_id=event_id,
        release_type=event_type,
        symbol=symbol.strip().upper(),
        event_at=event_at,
        reference_price=None,
        reference_at=None,
        observations={},
        issues=issues,
        event_time_source=event_time_source,
    )


def research_timed_event_reaction(
    *,
    event_id: str,
    event_type: str,
    event_at: datetime,
    event_time_source: str | None,
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
    extra_issues: list[str] | None = None,
) -> MarketReactionResult:
    """
    研究一个已经确定发生时间的事件之后的市场反应。

    不关心事件是：
    - CPI
    - PPI
    - Earnings
    - 其他未来事件

    这里只负责：
    - 分钟行情；
    - reference price；
    - 5m / 30m / 1h；
    - close；
    - 行情异常结构化返回。
    """

    try:
        market_data = prepare_timed_event_market_data(
            event_id=event_id,
            event_type=event_type,
            event_at=event_at,
            symbol=symbol,
            provider=provider,
            as_of=as_of,
            extra_issues=extra_issues,
        )
    except MarketDataCapabilityError:
        return _timed_event_failure_result(
            event_id=event_id,
            event_type=event_type,
            event_at=event_at,
            event_time_source=event_time_source,
            symbol=symbol,
            reason="minute_data_capability_unavailable",
            extra_issues=extra_issues,
        )
    except MarketDataProviderError:
        return _timed_event_failure_result(
            event_id=event_id,
            event_type=event_type,
            event_at=event_at,
            event_time_source=event_time_source,
            symbol=symbol,
            reason="minute_data_provider_error",
            extra_issues=extra_issues,
        )

    reaction = replace(
        calculate_market_reaction(market_data),
        event_time_source=event_time_source,
    )

    close_result = build_close_observation(
        alignment=market_data,
        provider=provider,
    )
    if close_result is None:
        return reaction

    observations = {
        **reaction.observations,
        "close": close_result,
    }
    issues = list(reaction.issues)

    if close_result.reason in {
        "daily_data_capability_unavailable",
        "daily_data_provider_error",
    }:
        issues.append(close_result.reason)

    return replace(
        reaction,
        observations=observations,
        issues=issues,
    )


def research_event_reaction(
    *,
    release: MacroReleaseEvent,
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
) -> MarketReactionResult:
    """准备行情并计算所有市场反应窗口。"""
    resolution = resolve_event_time(
        release,
        as_of=as_of,
    )

    if resolution.event_at is None:
        return MarketReactionResult(
            release_id=release.release_id,
            release_type=release.release_type,
            symbol=symbol.strip().upper(),
            event_at=None,
            reference_price=None,
            reference_at=None,
            observations={},
            issues=[
                resolution.reason
                or "event_time_unavailable"
            ],
            event_time_source=(
                resolution.event_time_source
            ),
        )
    extra_issues = list(resolution.warnings)

    return research_timed_event_reaction(
        event_id=release.release_id,
        event_type=release.release_type,
        event_at=resolution.event_at,
        event_time_source=resolution.event_time_source,
        symbol=symbol,
        provider=provider,
        as_of=as_of,
        extra_issues=extra_issues,
    )
