from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from stock_agent.macro.models.release import (
    MacroReleaseEvent,
    MacroReleaseType,
)
from stock_agent.market.provider import MarketDataProvider
from stock_agent.market_reaction.history import (
    select_historical_releases,
)
from stock_agent.market_reaction.multi_symbol import (
    MultiSymbolEventReaction,
    normalize_symbols,
    research_multi_symbol_event_reaction,
)


@dataclass(frozen=True)
class HistoricalMultiSymbolReaction:
    """多次同类宏观事件下，多只证券的市场反应。"""

    release_type: MacroReleaseType
    symbols: tuple[str, ...]
    before: datetime
    as_of: datetime

    events: list[MultiSymbolEventReaction]


def research_historical_multi_symbol_reactions(
    *,
    releases: Sequence[MacroReleaseEvent],
    release_type: MacroReleaseType,
    symbols: Sequence[str],
    before: datetime,
    limit: int,
    provider: MarketDataProvider,
    as_of: datetime,
) -> HistoricalMultiSymbolReaction:
    """查询最近 N 次同类宏观事件下，多只证券的反应。"""

    # 1. 先校验并规范化证券列表。
    normalized_symbols = normalize_symbols(symbols)

    # 2. 选择最近 N 次满足时间条件的历史事件。
    selected_releases = select_historical_releases(
        releases,
        release_type=release_type,
        before=before,
        as_of=as_of,
        limit=limit,
    )
    events: list[MultiSymbolEventReaction] = []

    for release in selected_releases:
        result = research_multi_symbol_event_reaction(
            release=release,
            symbols=normalized_symbols,
            provider=provider,
            as_of=as_of,
        )
        events.append(result)

    return HistoricalMultiSymbolReaction(
        release_type=release_type,
        symbols=normalized_symbols,
        before=before,
        as_of=as_of,
        events=events,
    )
