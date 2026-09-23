from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from longbridge.openapi import (
    AdjustType,
    OpenApiException,
    Period,
    TradeSessions,
)

from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.longbridge.longbridge_mapper import (
    map_longbridge_quote,
    to_longbridge_symbol,
)
from stock_agent.market.longbridge.longbridge_provider import (
    LongbridgeMarketDataProvider,
)


NEW_YORK = ZoneInfo("America/New_York")


def raw_quote(
    *,
    symbol: str = "NVDA.US",
    price: str = "200",
    timestamp: datetime,
    **sessions,
):
    return SimpleNamespace(
        symbol=symbol,
        last_done=Decimal(price),
        timestamp=timestamp,
        pre_market_quote=sessions.get("pre_market_quote"),
        post_market_quote=sessions.get("post_market_quote"),
        overnight_quote=sessions.get("overnight_quote"),
    )


def raw_bar(timestamp: datetime, price: int):
    return SimpleNamespace(
        timestamp=timestamp,
        open=Decimal(price),
        high=Decimal(price + 2),
        low=Decimal(price - 1),
        close=Decimal(price + 1),
        volume=1_000_000,
    )


class RecordingQuoteContext:
    def __init__(self, *, quotes=None, bars=None, error=None):
        self.quotes = [] if quotes is None else quotes
        self.bars = [] if bars is None else bars
        self.error = error
        self.quote_symbols = None
        self.history_args = None
        self.candlestick_args = None

    def quote(self, symbols):
        self.quote_symbols = symbols
        if self.error is not None:
            raise self.error
        return self.quotes

    def history_candlesticks_by_offset(self, *args):
        self.history_args = args
        if self.error is not None:
            raise self.error
        return self.bars

    def candlesticks(self, *args):
        self.candlestick_args = args
        if self.error is not None:
            raise self.error
        return self.bars


def test_quote_uses_latest_session_and_normalizes_symbol():
    regular_at = datetime(2026, 9, 22, 16, 0)
    post_at = datetime(2026, 9, 22, 18, 0)
    expected_post_at = post_at.astimezone().astimezone(NEW_YORK)
    context = RecordingQuoteContext(
        quotes=[
            raw_quote(
                timestamp=regular_at,
                post_market_quote=SimpleNamespace(
                    last_done=Decimal("203"),
                    timestamp=post_at,
                ),
            )
        ]
    )
    provider = LongbridgeMarketDataProvider(quote_context=context)

    quote = provider.get_quote(
        " nvda ",
        as_of=expected_post_at + timedelta(minutes=1),
    )

    assert context.quote_symbols == ["NVDA.US"]
    assert quote is not None
    assert quote.symbol == "NVDA"
    assert quote.price == Decimal("203")
    assert quote.session == "post"
    assert quote.quoted_at == expected_post_at
    assert quote.is_delayed is None


def test_quote_without_valid_price_returns_none():
    value = raw_quote(
        price="0",
        timestamp=datetime(2026, 9, 22, 16, 0, tzinfo=NEW_YORK),
    )

    assert map_longbridge_quote(
        value,
        received_at=datetime.now(timezone.utc),
        as_of=datetime(2026, 9, 23, tzinfo=timezone.utc),
        is_delayed=None,
    ) is None


def test_completed_daily_bars_return_requested_limit():
    first_day = datetime(2026, 6, 1, 9, 30, tzinfo=NEW_YORK)
    source_bars = [
        raw_bar(first_day + timedelta(days=index), 100 + index)
        for index in range(61)
    ]
    as_of = source_bars[-1].timestamp.replace(
        hour=12,
        minute=0,
        tzinfo=NEW_YORK,
    )
    context = RecordingQuoteContext(bars=source_bars)
    provider = LongbridgeMarketDataProvider(quote_context=context)

    bars = provider.get_bars(
        "nvda",
        as_of=as_of,
        timeframe="1d",
        limit=60,
    )

    assert len(bars) == 60
    assert all(bar.is_complete for bar in bars)
    assert all(bar.updated_at == bar.end_at for bar in bars)
    assert all(bar.data_mode == "historical" for bar in bars)
    assert context.history_args == (
        "NVDA.US",
        Period.Day,
        AdjustType.ForwardAdjust,
        False,
        61,
        as_of,
        TradeSessions.Intraday,
    )


def test_include_incomplete_uses_current_candlesticks():
    current_day = datetime(2026, 9, 22, 9, 30, tzinfo=NEW_YORK)
    as_of = current_day.replace(hour=12)
    context = RecordingQuoteContext(
        bars=[raw_bar(current_day, 200)]
    )
    provider = LongbridgeMarketDataProvider(quote_context=context)

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
        include_incomplete=True,
    )

    assert len(bars) == 1
    assert bars[0].is_complete is False
    assert bars[0].data_mode == "live"
    assert context.candlestick_args == (
        "NVDA.US",
        Period.Day,
        60,
        AdjustType.ForwardAdjust,
        TradeSessions.Intraday,
    )


def test_no_data_and_provider_errors_are_distinct():
    empty_provider = LongbridgeMarketDataProvider(
        quote_context=RecordingQuoteContext()
    )
    as_of = datetime.now(timezone.utc)

    assert empty_provider.get_quote("NVDA", as_of=as_of) is None
    assert empty_provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
    ) == []

    sdk_error = OpenApiException(
        "http",
        99999,
        "fixture-trace",
        "fixture provider failure",
    )
    failing_provider = LongbridgeMarketDataProvider(
        quote_context=RecordingQuoteContext(error=sdk_error)
    )

    with pytest.raises(MarketDataProviderError) as quote_error:
        failing_provider.get_quote("NVDA", as_of=as_of)
    assert quote_error.value.__cause__ is sdk_error

    with pytest.raises(MarketDataProviderError) as bar_error:
        failing_provider.get_bars(
            "NVDA",
            as_of=as_of,
            timeframe="1d",
            limit=60,
        )
    assert bar_error.value.__cause__ is sdk_error


def test_symbol_mapping_rejects_empty_symbol():
    with pytest.raises(ValueError, match="symbol must not be empty"):
        to_longbridge_symbol("  ")
