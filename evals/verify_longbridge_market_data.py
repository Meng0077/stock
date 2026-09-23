"""Day22 Longbridge Market Data 在线验收。

本脚本会真实访问 Longbridge OpenAPI。

验收目标：
    1. NVDA 和 AMD 都能通过同一个 Provider 查询；
    2. Quote 返回项目自己的 Quote 模型；
    3. Daily Bar 至少能获取 60 根；
    4. Bar 按时间从旧到新排列；
    5. Provider 没有把 Longbridge symbol / 类型泄漏给上层；
    6. source / adjustment / data_mode 等 canonical 字段有效。

运行：

    PYTHONPATH=backend/src \
    backend/.venv/bin/python \
    backend/examples/verify_longbridge_market_data.py
"""

from datetime import datetime, timezone

from stock_agent.market.longbridge_config import (
    build_longbridge_market_provider,
)
from stock_agent.market.schemas import (
    Bar,
    Quote,
)


def verify_quote(
    provider,
    symbol: str,
) -> None:
    """验证指定 ticker 的真实 Quote 查询。

    Args:
        provider:
            已初始化的 LongbridgeMarketDataProvider。

        symbol:
            系统内部 ticker，例如 "NVDA"。

    验证：
        - 返回的是项目统一 Quote；
        - symbol 没有泄漏 ".US"；
        - source / data_mode 正确；
        - 时间字段带时区。
    """

    as_of = datetime.now(
        timezone.utc
    )

    quote = provider.get_quote(
        symbol,
        as_of=as_of,
    )

    assert quote is not None

    assert isinstance(
        quote,
        Quote,
    )

    assert quote.symbol == symbol

    # 上层应该只看到 "NVDA"，
    # 而不是 Longbridge 的 "NVDA.US"。
    assert not quote.symbol.endswith(
        ".US"
    )

    assert quote.source == "longbridge"
    assert quote.data_mode == "live"

    assert quote.price > 0

    assert (
        quote.quoted_at.tzinfo
        is not None
    )

    assert (
        quote.received_at.tzinfo
        is not None
    )

    print(
        "QUOTE",
        symbol,
        quote,
    )


def verify_daily_bars(
    provider,
    symbol: str,
) -> None:
    """验证指定 ticker 的真实 Daily Bar 查询。

    Args:
        provider:
            已初始化的真实行情 Provider。

        symbol:
            系统内部 ticker。

    验证：
        - 至少返回 60 根历史 Daily Bar；
        - 返回项目统一 Bar；
        - 时间顺序 oldest -> newest；
        - completed-only 查询不包含未完成 K；
        - 使用统一复权口径；
        - 不暴露 Longbridge symbol。
    """

    as_of = datetime.now(
        timezone.utc
    )

    bars = provider.get_bars(
        symbol,
        as_of=as_of,
        timeframe="1d",
        limit=60,
        include_incomplete=False,
    )

    assert len(bars) == 60

    assert all(
        isinstance(bar, Bar)
        for bar in bars
    )

    assert all(
        bar.symbol == symbol
        for bar in bars
    )

    assert all(
        not bar.symbol.endswith(".US")
        for bar in bars
    )

    assert all(
        bar.timeframe == "1d"
        for bar in bars
    )

    assert all(
        bar.is_complete
        for bar in bars
    )

    assert all(
        bar.adjustment
        == "forward_adjusted"
        for bar in bars
    )

    assert all(
        bar.source == "longbridge"
        for bar in bars
    )

    # 必须按照 oldest -> newest 返回。
    assert bars == sorted(
        bars,
        key=lambda bar: bar.start_at,
    )

    print(
        "BARS",
        symbol,
        "count=",
        len(bars),
    )

    print(
        "first:",
        bars[0].start_at,
        bars[0].close,
    )

    print(
        "last:",
        bars[-1].start_at,
        bars[-1].close,
    )

def verify_include_incomplete(
    provider,
) -> None:
    """验证 include_incomplete=True 的返回契约。

    当前市场未必正处于 regular session，
    因此不强制要求最后一根一定 incomplete。

    验证：
        - 最多返回 limit 根；
        - 时间顺序 oldest -> newest；
        - 如果存在 incomplete Bar，它必须位于最后；
        - incomplete Bar 必须标记为 live。
    """

    as_of = datetime.now(
        timezone.utc
    )

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
        include_incomplete=True,
    )

    assert bars
    assert len(bars) <= 60

    assert bars == sorted(
        bars,
        key=lambda bar: bar.start_at,
    )

    incomplete_bars = [
        bar
        for bar in bars
        if not bar.is_complete
    ]

    # Daily 查询最多应该只有最后一根正在形成。
    assert len(incomplete_bars) <= 1

    if incomplete_bars:
        current_bar = incomplete_bars[0]

        assert current_bar is bars[-1]
        assert current_bar.data_mode == "live"

    print(
        "include_incomplete:",
        len(bars),
        "current_bar=",
        bool(incomplete_bars),
    )


class EmptyQuoteContext:
    """模拟 Longbridge 正常请求成功，但没有任何行情数据。"""

    def quote(
        self,
        symbols,
    ):
        """模拟 quote API 返回空结果。"""

        return []

    def candlesticks(
        self,
        *args,
        **kwargs,
    ):
        """模拟当前 K 线接口返回空结果。"""

        return []

    def history_candlesticks_by_offset(
        self,
        *args,
        **kwargs,
    ):
        """模拟历史 K 线接口返回空结果。"""

        return []

def verify_no_data() -> None:
    """验证“无数据”和“供应商失败”没有被混淆。"""

    provider = (
        LongbridgeMarketDataProvider(
            quote_context=EmptyQuoteContext()
        )
    )

    as_of = datetime.now(
        timezone.utc
    )

    quote = provider.get_quote(
        "NVDA",
        as_of=as_of,
    )

    assert quote is None

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
    )

    assert bars == []

from longbridge.openapi import (
    OpenApiException,
)


class FailingQuoteContext:
    """模拟 Longbridge API 调用失败。"""

    def quote(
        self,
        symbols,
    ):
        """模拟 quote 请求失败。"""

        raise OpenApiException(
            99999,
            "fixture provider failure",
        )

    def candlesticks(
        self,
        *args,
        **kwargs,
    ):
        """模拟 K 线请求失败。"""

        raise OpenApiException(
            99999,
            "fixture provider failure",
        )

    def history_candlesticks_by_offset(
        self,
        *args,
        **kwargs,
    ):
        """模拟历史 K 线请求失败。"""

        raise OpenApiException(
            99999,
            "fixture provider failure",
        )

def verify_quote_provider_error() -> None:
    """验证 Longbridge quote 异常不会被错误转换成 None。"""

    provider = (
        LongbridgeMarketDataProvider(
            quote_context=FailingQuoteContext()
        )
    )

    try:
        provider.get_quote(
            "NVDA",
            as_of=datetime.now(
                timezone.utc
            ),
        )
    except MarketDataProviderError as exc:
        assert isinstance(
            exc.__cause__,
            OpenApiException,
        )
    else:
        raise AssertionError(
            "expected MarketDataProviderError"
        )

def verify_bars_provider_error() -> None:
    """验证 Longbridge Bar 异常不会被错误转换成空列表。"""

    provider = (
        LongbridgeMarketDataProvider(
            quote_context=FailingQuoteContext()
        )
    )

    try:
        provider.get_bars(
            "NVDA",
            as_of=datetime.now(
                timezone.utc
            ),
            timeframe="1d",
            limit=60,
        )
    except MarketDataProviderError as exc:
        assert isinstance(
            exc.__cause__,
            OpenApiException,
        )
    else:
        raise AssertionError(
            "expected MarketDataProviderError"
        )

def main() -> None:
    """运行 Day22 Longbridge happy-path 在线验收。"""

    provider = (
        build_longbridge_market_provider()
    )

    # 同一个 Provider 支持动态 ticker。
    for symbol in (
        "NVDA",
        "AMD",
    ):
        verify_quote(
            provider,
            symbol,
        )

        verify_daily_bars(
            provider,
            symbol,
        )

    print(
        "Day22 Longbridge market "
        "data verification passed."
    )


if __name__ == "__main__":
    main()