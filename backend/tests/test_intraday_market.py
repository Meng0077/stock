from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from longbridge.openapi import AdjustType, Period, TradeSession, TradeSessions
from pydantic import ValidationError

from stock_agent.market.errors import (
    MarketDataCapabilityError,
    MarketDataProviderError,
)
from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.intraday import HistoricalMinuteBarsRequest, IntradayBar
from stock_agent.market.intraday_coverage import inspect_intraday_coverage
from stock_agent.market.longbridge.longbridge_mapper import (
    map_longbridge_intraday_bar,
)
from stock_agent.market.longbridge.longbridge_provider import (
    LongbridgeMarketDataProvider,
)
from stock_agent.quality.intraday import validate_intraday_bars


NEW_YORK = ZoneInfo("America/New_York")
START_AT = datetime(2026, 9, 25, 9, 30, tzinfo=NEW_YORK)


def make_bar(
    start_at: datetime,
    *,
    session: str = "regular",
    close: str = "180.5",
) -> IntradayBar:
    end_at = start_at + timedelta(minutes=1)
    return IntradayBar(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        open=Decimal("180"),
        high=Decimal("181"),
        low=Decimal("179"),
        close=Decimal(close),
        volume=100,
        is_complete=True,
        adjustment="raw",
        updated_at=end_at,
        received_at=end_at,
        source="fixture",
        data_mode="fixture",
        session=session,
    )


def make_request(
    *,
    start_at: datetime = START_AT,
    end_at: datetime = START_AT + timedelta(minutes=3),
) -> HistoricalMinuteBarsRequest:
    return HistoricalMinuteBarsRequest(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        as_of=end_at,
    )


def raw_bar(
    start_at: datetime,
    *,
    session=TradeSession.Intraday,
    close: str = "180.5",
):
    return SimpleNamespace(
        timestamp=start_at,
        open=Decimal("180"),
        high=Decimal("181"),
        low=Decimal("179"),
        close=Decimal(close),
        volume=100,
        trade_session=session,
    )


class PagedQuoteContext:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def history_candlesticks_by_offset(self, *args):
        self.calls.append(args)
        return self.pages.pop(0)


def test_intraday_request_requires_aware_timestamps_and_valid_window():
    with pytest.raises(ValidationError, match="timezone info"):
        HistoricalMinuteBarsRequest(
            symbol="NVDA",
            start_at=datetime(2026, 9, 25, 9, 30),
            end_at=START_AT + timedelta(minutes=1),
            as_of=START_AT + timedelta(minutes=1),
        )

    with pytest.raises(ValidationError, match="must not end after as_of"):
        HistoricalMinuteBarsRequest(
            symbol="NVDA",
            start_at=START_AT,
            end_at=START_AT + timedelta(minutes=2),
            as_of=START_AT + timedelta(minutes=1),
        )


def test_fixture_intraday_distinguishes_empty_data_and_missing_capability():
    empty_provider = FixtureMarketDataProvider(
        quotes={},
        bars={("NVDA", "1m"): []},
    )
    request = make_request()

    assert empty_provider.get_intraday_bars(
        "NVDA",
        start_at=request.start_at,
        end_at=request.end_at,
        as_of=request.as_of,
    ) == []

    missing_provider = FixtureMarketDataProvider(quotes={}, bars={})
    with pytest.raises(
        MarketDataCapabilityError,
        match="minute bars are not configured",
    ):
        missing_provider.get_intraday_bars(
            "NVDA",
            start_at=request.start_at,
            end_at=request.end_at,
            as_of=request.as_of,
        )


def test_fixture_intraday_filters_and_sorts_completed_bars():
    request = make_request()
    first = make_bar(START_AT)
    second = make_bar(START_AT + timedelta(minutes=1))
    incomplete = make_bar(START_AT + timedelta(minutes=2)).model_copy(
        update={"is_complete": False}
    )
    provider = FixtureMarketDataProvider(
        quotes={},
        bars={("NVDA", "1m"): [second, incomplete, first]},
    )

    result = provider.get_intraday_bars(
        "NVDA",
        start_at=request.start_at,
        end_at=request.end_at,
        as_of=request.as_of,
    )

    assert result == [first, second]


def test_intraday_quality_accepts_first_bar_without_runtime_error():
    result = validate_intraday_bars(
        request=make_request(),
        bars=[make_bar(START_AT)],
        required_sessions=["regular"],
    )

    assert result.status == "usable"
    assert result.issues == []


@pytest.mark.parametrize(
    ("bars", "issue_code"),
    [
        (
            [
                make_bar(START_AT + timedelta(minutes=1)),
                make_bar(START_AT),
            ],
            "intraday_not_sorted",
        ),
        (
            [make_bar(START_AT), make_bar(START_AT)],
            "duplicate_intraday_bar",
        ),
    ],
)
def test_intraday_quality_rejects_invalid_order(bars, issue_code):
    result = validate_intraday_bars(
        request=make_request(),
        bars=bars,
        required_sessions=["regular"],
    )

    assert result.status == "rejected"
    assert result.issues[0].code == issue_code


def test_intraday_coverage_reports_observed_sessions():
    pre_at = START_AT.replace(hour=8)
    request = make_request(
        start_at=pre_at,
        end_at=START_AT + timedelta(minutes=1),
    )

    coverage = inspect_intraday_coverage(
        request=request,
        bars=[
            make_bar(pre_at, session="pre"),
            make_bar(START_AT, session="regular"),
        ],
        required_sessions={"pre", "regular", "post"},
    )

    assert coverage.status == "partially_observed"
    assert coverage.observed_counts == {
        "post": 0,
        "pre": 1,
        "regular": 1,
    }
    assert coverage.unobserved_sessions == ["post"]


@pytest.mark.parametrize(
    ("raw_session", "expected"),
    [
        (TradeSession.Pre, "pre"),
        (TradeSession.Intraday, "regular"),
        (TradeSession.Post, "post"),
        (TradeSession.Overnight, "overnight"),
    ],
)
def test_longbridge_intraday_mapper_preserves_session(raw_session, expected):
    bar = map_longbridge_intraday_bar(
        raw_bar(START_AT, session=raw_session),
        symbol="NVDA",
        received_at=START_AT + timedelta(minutes=2),
        as_of=START_AT + timedelta(minutes=2),
    )

    assert bar.session == expected
    assert bar.timeframe == "1m"
    assert bar.start_at.tzinfo == NEW_YORK
    assert bar.adjustment == "raw"
    assert bar.source == "longbridge"


def test_longbridge_intraday_provider_paginates_and_deduplicates():
    request = make_request(
        start_at=START_AT,
        end_at=START_AT + timedelta(minutes=3),
    )
    context = PagedQuoteContext(
        pages=[
            [
                raw_bar(START_AT + timedelta(minutes=2)),
                raw_bar(START_AT + timedelta(minutes=1)),
            ],
            [
                raw_bar(START_AT + timedelta(minutes=1)),
                raw_bar(START_AT),
            ],
        ]
    )
    provider = LongbridgeMarketDataProvider(quote_context=context)

    bars = provider.get_intraday_bars(
        "NVDA",
        start_at=request.start_at,
        end_at=request.end_at,
        as_of=request.as_of,
    )

    assert [bar.start_at for bar in bars] == [
        START_AT,
        START_AT + timedelta(minutes=1),
        START_AT + timedelta(minutes=2),
    ]
    assert context.calls[0] == (
        "NVDA.US",
        Period.Min_1,
        AdjustType.NoAdjust,
        False,
        1000,
        request.end_at,
        TradeSessions.All,
    )
    assert context.calls[1][5] == START_AT + timedelta(minutes=1)


def test_longbridge_intraday_provider_rejects_conflicting_page_boundary():
    context = PagedQuoteContext(
        pages=[
            [
                raw_bar(START_AT + timedelta(minutes=2)),
                raw_bar(START_AT + timedelta(minutes=1)),
            ],
            [
                raw_bar(
                    START_AT + timedelta(minutes=1),
                    close="180.75",
                ),
                raw_bar(START_AT),
            ],
        ]
    )
    provider = LongbridgeMarketDataProvider(quote_context=context)

    with pytest.raises(MarketDataProviderError, match="Conflicting minute bars"):
        provider.get_intraday_bars(
            "NVDA",
            start_at=START_AT,
            end_at=START_AT + timedelta(minutes=3),
            as_of=START_AT + timedelta(minutes=3),
        )
