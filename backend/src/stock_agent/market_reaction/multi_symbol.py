from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from stock_agent.market.provider import MarketDataProvider
from stock_agent.macro.models.release import MacroReleaseEvent, MacroReleaseType
from stock_agent.market_reaction.models import MarketReactionResult
from stock_agent.market_reaction.service import research_event_reaction


@dataclass(frozen=True)
class MultiSymbolEventReaction:
    """同一次宏观事件下，多个证券的市场反应。"""

    release_id: str
    release_type: MacroReleaseType
    release_date: date
    event_at: datetime | None

    symbols: tuple[str, ...]
    reactions: dict[str, MarketReactionResult]


def normalize_symbols(
    symbols: Sequence[str],
) -> tuple[str, ...]:
    """规范化证券代码，并按首次出现顺序去重。"""

    if isinstance(symbols, str):
        raise TypeError(
            "symbols must be a sequence of symbols, not a single string"
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("symbol must not be empty")

        if normalized_symbol in seen:
            continue
        normalized.append(normalized_symbol)
        seen.add(normalized_symbol)
    if not normalized:
        raise ValueError("symbols must not be empty")

    return tuple(normalized)


def research_multi_symbol_event_reaction(
    *,
    release: MacroReleaseEvent,
    symbols: Sequence[str],
    provider: MarketDataProvider,
    as_of: datetime,
) -> MultiSymbolEventReaction:
    """查询同一次宏观事件下，多个证券的市场反应。"""

    normalized_symbols = normalize_symbols(symbols=symbols)
    reactions: dict[str, MarketReactionResult] = {}

    for symbol in normalized_symbols:
        reactions[symbol] = research_event_reaction(
            release=release,
            symbol=symbol,
            provider=provider,
            as_of=as_of,
        )

    # normalize_symbols 已保证列表非空。
    # 所有结果属于同一次宏观事件，事件时间相同。
    first_reaction = reactions[normalized_symbols[0]]

    return MultiSymbolEventReaction(
        release_id=release.release_id,
        release_type=release.release_type,
        event_at=first_reaction.event_at,
        symbols=normalized_symbols,
        reactions=reactions,
        release_date=release.release_date,
    )
