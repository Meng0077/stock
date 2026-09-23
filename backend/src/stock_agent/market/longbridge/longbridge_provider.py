from datetime import datetime, timezone

from longbridge.openapi import (
    AdjustType,
    OpenApiException,
    QuoteContext,
    TradeSessions,
)

from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.longbridge.longbridge_mapper import (
    map_longbridge_bar,
    map_longbridge_quote,
    to_longbridge_period,
    to_longbridge_symbol,
)
from stock_agent.market.schemas import (
    Bar,
    BarTimeframe,
    Quote,
)


class LongbridgeMarketDataProvider:
    """Longbridge OpenAPI 的 MarketDataProvider 实现。

    负责：
        - 接收系统内部 symbol，例如 "NVDA"；
        - 调用 Longbridge QuoteContext；
        - 把 Longbridge 原始数据交给 mapper；
        - 返回项目统一的 Quote / Bar。

    不负责：
        - 把“英伟达”解析成 NVDA；
        - 暴露 Longbridge 原始字段给上层；
        - 计算 MA / ATR 等技术指标；
        - 做趋势判断或交易决策；
        - 管理 Agent 对话状态。
    """

    def __init__(
        self,
        *,
        quote_context: QuoteContext,
    ) -> None:
        """注入 Longbridge 行情客户端。

        Args:
            quote_context:
                已完成认证和初始化的 Longbridge QuoteContext。

        Provider 不主动创建认证配置，
        避免行情查询逻辑和认证逻辑耦合。
        """

        self._quote_context = quote_context

    def get_quote(
        self,
        symbol: str,
        *,
        as_of: datetime,
    ) -> Quote | None:
        """获取指定 symbol 的统一 Quote。

        Args:
            symbol:
                系统内部 ticker，例如 "NVDA"。

            as_of:
                本次研究允许使用的最大市场信息时间。

        Returns:
            转换后的 Quote。

            如果没有可用行情，返回 None。

            1. symbol -> Longbridge symbol；
            2. 调用 quote API；
            3. 记录 received_at；
            4. raw quote -> Quote；
            5. 做 point-in-time 校验；
            6. 返回结果。
        """

        longbridge_symbol = to_longbridge_symbol(symbol)

        try:
            raw_quotes = self._quote_context.quote([longbridge_symbol])
        except OpenApiException as exc:
            raise MarketDataProviderError(
                f"Longbridge quote request failed: code={exc.code}, message={exc.message}"
            ) from exc

        received_at = datetime.now(timezone.utc)
        if not raw_quotes:
            return None
        raw_quote = raw_quotes[0]

        return map_longbridge_quote(
            raw_quote,
            received_at=received_at,
            as_of=as_of,
            is_delayed=False
        )


    def get_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        timeframe: BarTimeframe,
        limit: int,
        include_incomplete: bool = False,
    ) -> list[Bar]:
        """获取指定 symbol 的统一 Bar 序列。

        Args:
            symbol:
                系统内部 ticker。

            as_of:
                本次研究允许使用的最大市场信息时间。

            timeframe:
                K 线周期，例如 "1d"。

            limit:
                最多返回多少根 Bar。

            include_incomplete:
                是否允许返回当前正在形成的 Bar。

        Returns:
            按时间从旧到新排列的 Bar。

            1. 校验 limit；
            2. symbol -> Longbridge symbol；
            3. timeframe -> Longbridge period；
            4. 调用 candlestick API；
            5. 记录 received_at；
            6. raw candles -> list[Bar]；
            7. 根据 as_of 过滤；
            8. 根据 include_incomplete 过滤；
            9. 排序；
            10. 应用 limit。
        """
        if limit <= 0:
            raise ValueError(
                "limit must be greater than 0"
            )

        longbridge_symbol = to_longbridge_symbol(symbol)
        period = to_longbridge_period(timeframe)
        request_count = min(limit, 1000)
        try:
            if include_incomplete:
                raw_bars = self._quote_context.candlesticks(
                    longbridge_symbol,
                    period,
                    request_count,
                    AdjustType.ForwardAdjust,
                    TradeSessions.Intraday,
                )
            else:
                raw_bars = self._quote_context.history_candlesticks_by_offset(
                    longbridge_symbol,
                    period,
                    AdjustType.ForwardAdjust,
                    False,
                    request_count,
                    as_of,
                    TradeSessions.Intraday,
                )
        except OpenApiException as exc:
            raise MarketDataProviderError(
                f"Longbridge quote request failed: code={exc.code}, message={exc.message}"
            ) from exc


        received_at = datetime.now(timezone.utc)

        bars = [
            map_longbridge_bar(
                raw_bar,
                symbol=symbol.strip().upper(),
                timeframe=timeframe,
                received_at=received_at,
                as_of=as_of,
            ) for raw_bar in raw_bars
        ]

        # 当前 Day22 不做历史盘中 replay。
        #
        # completed-only 时，
        # 只允许已经结束的 K 线。

        if not include_incomplete:
            bars = [ bar for bar in bars if bar.is_complete]
        bars.sort(key=lambda bar: bar.start_at)
        return bars[-limit:]
