"""Day22 Longbridge Market Data 在线验收。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)
from stock_agent.market.schemas import Bar, Quote


ROOT = Path(__file__).resolve().parents[1]


def verify_quote(provider, symbol: str) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(seconds=5)
    quote = provider.get_quote(symbol, as_of=as_of)

    assert isinstance(quote, Quote)
    assert quote.symbol == symbol
    assert not quote.symbol.endswith(".US")
    assert quote.price > 0
    assert quote.source == "longbridge"
    assert quote.data_mode == "live"
    assert quote.quoted_at.tzinfo is not None
    assert quote.received_at.tzinfo is not None

    print("QUOTE", symbol, quote)


def verify_daily_bars(provider, symbol: str) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(seconds=5)
    bars = provider.get_bars(
        symbol,
        as_of=as_of,
        timeframe="1d",
        limit=60,
    )

    assert len(bars) == 60
    assert all(isinstance(bar, Bar) for bar in bars)
    assert all(bar.symbol == symbol for bar in bars)
    assert all(bar.timeframe == "1d" for bar in bars)
    assert all(bar.is_complete for bar in bars)
    assert all(bar.updated_at == bar.end_at for bar in bars)
    assert all(bar.adjustment == "forward_adjusted" for bar in bars)
    assert all(bar.source == "longbridge" for bar in bars)
    assert all(bar.data_mode == "historical" for bar in bars)
    assert bars == sorted(bars, key=lambda bar: bar.start_at)

    print(
        "BARS",
        symbol,
        "count=",
        len(bars),
        "first=",
        bars[0].start_at,
        "last=",
        bars[-1].start_at,
    )


def main() -> None:
    load_dotenv(ROOT / "backend" / ".env", override=False)
    provider = build_longbridge_market_provider()

    for symbol in ("NVDA", "AMD"):
        verify_quote(provider, symbol)
        verify_daily_bars(provider, symbol)

    print("Day22 Longbridge market data verification passed.")


if __name__ == "__main__":
    main()
