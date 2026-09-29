from dataclasses import replace
from datetime import datetime

from stock_agent.macro.models.release import (
    MacroReleaseEvent,
)
from stock_agent.market.errors import MarketDataCapabilityError, MarketDataProviderError
from stock_agent.market.provider import MarketDataProvider
from stock_agent.market_reaction.alignment import (
    prepare_event_market_data,
)
from stock_agent.market_reaction.calculator import (
    calculate_market_reaction,
)
from stock_agent.market_reaction.close_data import (
    build_close_observation,
)
from stock_agent.market_reaction.event_time import resolve_event_time
from stock_agent.market_reaction.models import MarketReactionResult


def _minute_failure_result(
    *,
    release: MacroReleaseEvent,
    symbol: str,
    as_of: datetime,
    reason: str,
) -> MarketReactionResult:
    """分钟行情不可用时，返回结构化的失败结果。"""

    resolution = resolve_event_time(
        release,
        as_of=as_of,
    )

    issues = [reason]

    if resolution.warning:
        issues.append(resolution.warning)

    return MarketReactionResult(
        release_id=release.release_id,
        release_type=release.release_type,
        symbol=symbol.strip().upper(),
        event_at=resolution.event_at,
        reference_price=None,
        reference_at=None,
        observations={},
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

    try:
        alignment = prepare_event_market_data(
            release=release,
            symbol=symbol,
            provider=provider,
            as_of=as_of,
        )
    except MarketDataCapabilityError:
        return _minute_failure_result(
            release=release,
            symbol=symbol,
            as_of=as_of,
            reason="minute_data_capability_unavailable",
        )
    except MarketDataProviderError:
        return _minute_failure_result(
            release=release,
            symbol=symbol,
            as_of=as_of,
            reason="minute_data_provider_error",
        )

    reaction = calculate_market_reaction(alignment)

    close_result = build_close_observation(
        alignment=alignment,
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
