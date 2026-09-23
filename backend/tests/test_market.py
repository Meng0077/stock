from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from stock_agent.market.fixture_provider import FixtureMarketDataProvider
from stock_agent.market.fixtures import FIXTURE_BARS, FIXTURE_QUOTES
from stock_agent.market.schemas import Bar, Quote


NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture
def provider() -> FixtureMarketDataProvider:
    return FixtureMarketDataProvider(
        quotes=FIXTURE_QUOTES,
        bars=FIXTURE_BARS,
    )


def test_quote_supports_dynamic_symbol_and_received_time(provider):
    before_received = datetime(
        2026,
        9,
        21,
        16,
        0,
        tzinfo=NEW_YORK,
    )
    after_received = datetime(
        2026,
        9,
        21,
        16,
        0,
        2,
        tzinfo=NEW_YORK,
    )

    assert provider.get_quote("NVDA", as_of=before_received) is None
    nvda = provider.get_quote(" nvda ", as_of=after_received)
    assert nvda.symbol == "NVDA"
    assert nvda.data_mode == "fixture"
    assert nvda.source == "local_fixture"
    assert nvda.is_delayed is False
    assert provider.get_quote("amd", as_of=after_received).symbol == "AMD"
    assert provider.get_quote("UNKNOWN", as_of=after_received) is None


def test_completed_bars_use_updated_time(provider):
    at_second_update = datetime(
        2026,
        9,
        18,
        16,
        0,
        tzinfo=NEW_YORK,
    )
    bars = provider.get_bars(
        "NVDA",
        as_of=at_second_update,
        timeframe="1d",
        limit=60,
    )

    # completed Bar 已在 16:00 更新完成；即使 received_at
    # 晚一秒，也不影响历史 Bar 按 updated_at 查询。
    assert [bar.start_at.day for bar in bars] == [17, 18]

    during_session = datetime(
        2026,
        9,
        21,
        15,
        0,
        tzinfo=NEW_YORK,
    )
    bars = provider.get_bars(
        "NVDA",
        as_of=during_session,
        timeframe="1d",
        limit=60,
    )
    assert len(bars) == 2
    assert all(bar.is_complete for bar in bars)
    assert all(bar.data_mode == "fixture" for bar in bars)
    assert all(bar.adjustment == "split_adjusted" for bar in bars)


def test_incomplete_bar_requires_explicit_opt_in_and_visible_snapshot(provider):
    before_snapshot = datetime(
        2026,
        9,
        21,
        14,
        0,
        tzinfo=NEW_YORK,
    )
    assert all(
        bar.is_complete
        for bar in provider.get_bars(
            "NVDA",
            as_of=before_snapshot,
            timeframe="1d",
            limit=60,
            include_incomplete=True,
        )
    )

    after_snapshot = datetime(
        2026,
        9,
        21,
        15,
        0,
        tzinfo=NEW_YORK,
    )
    bars = provider.get_bars(
        "NVDA",
        as_of=after_snapshot,
        timeframe="1d",
        limit=60,
        include_incomplete=True,
    )
    assert len(bars) == 3
    assert bars[-1].is_complete is False
    assert bars[-1].updated_at <= after_snapshot


def test_bar_limit_and_unknown_symbol(provider):
    as_of = datetime(2026, 9, 22, 12, 0, tzinfo=NEW_YORK)

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=1,
    )
    assert len(bars) == 1
    assert provider.get_bars(
        "UNKNOWN",
        as_of=as_of,
        timeframe="1d",
        limit=60,
    ) == []

    with pytest.raises(ValueError, match="limit must be greater than 0"):
        provider.get_bars(
            "NVDA",
            as_of=as_of,
            timeframe="1d",
            limit=0,
        )


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (Quote, "received_at"),
        (Bar, "updated_at"),
        (Bar, "received_at"),
    ],
)
def test_market_timestamps_require_timezone(model, field):
    source = (
        FIXTURE_QUOTES["NVDA"]
        if model is Quote
        else FIXTURE_BARS[("NVDA", "1d")][0]
    )
    data = source.model_dump()
    data[field] = datetime(2026, 9, 21, 12, 0)

    with pytest.raises(ValidationError, match="timestamp must be timezone-aware"):
        model.model_validate(data)
