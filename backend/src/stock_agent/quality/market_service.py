
from dataclasses import dataclass
from datetime import datetime

from stock_agent.market.schemas import Bar, Quote
from stock_agent.market.technical import (
    MarketTechnicalSnapshot,
    build_market_technical_snapshot,
)
from stock_agent.quality.bars import validate_bars
from stock_agent.quality.quote import MarketState, validate_quote
from stock_agent.quality.report import DataQualityReport

@dataclass(frozen=True)
class GuardedMarketAnalysis:
    # usable / degraded 报价可以附带质量状态展示；rejected 报价必须清空。
    current_quote: Quote | None

    # 技术分析结果；历史 K 线不合格时为 None。
    technical: MarketTechnicalSnapshot | None

    quality: DataQualityReport

def build_guarded_market_analysis(
    *,
    symbol: str,
    quote: Quote | None,
    bars: list[Bar],
    as_of: datetime,
    market_state: MarketState,
) -> GuardedMarketAnalysis:
    quote_quality = validate_quote(
        quote=quote,
        symbol=symbol,
        as_of=as_of,
        market_state=market_state,
    )

    bars_quality = validate_bars(
        bars=bars,
        symbol=symbol,
        as_of=as_of,
        timeframe="1d",
        required_completed_bars=60,
        allow_incomplete=False,
    )

    report = DataQualityReport(
        as_of=as_of,
        results=[quote_quality, bars_quality]
    )

    safe_quote = (
        quote
        if quote_quality.status != "rejected"
        else None
    )

    if bars_quality.status == "rejected":
        return GuardedMarketAnalysis(
            current_quote=safe_quote,
            technical=None,
            quality=report,
        )

    completed_bars = [bar for bar in bars if bar.is_complete]
    technical = build_market_technical_snapshot(
        symbol=symbol,
        quote=None,
        bars=completed_bars,
        is_live_query=False,
    )

    return GuardedMarketAnalysis(
        current_quote=safe_quote,
        technical=technical,
        quality=report,
    )
