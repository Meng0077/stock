from datetime import datetime, timezone

from longbridge.openapi import (
    AdjustType,
    OpenApiException,
    Period,
    QuoteContext,
    TradeSessions,
)

from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.intraday import (
    HistoricalMinuteBarsRequest,
    IntradayBar,
)
from stock_agent.market.longbridge.longbridge_mapper import (
    map_longbridge_bar,
    map_longbridge_intraday_bar,
    map_longbridge_quote,
    to_longbridge_adjust_type,
    to_longbridge_period,
    to_longbridge_symbol,
)
from stock_agent.market.schemas import (
    Bar,
    BarTimeframe,
    PriceAdjustment,
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
            is_delayed=None,
        )


    def get_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        timeframe: BarTimeframe,
        limit: int,
        include_incomplete: bool = False,
        adjustment: PriceAdjustment | None = None,
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
        normalized_adjustment = adjustment or "forward_adjusted"
        adjust_type = to_longbridge_adjust_type(normalized_adjustment)
        request_count = min(
            limit if include_incomplete else limit + 1,
            1000,
        )
        try:
            if include_incomplete:
                raw_bars = self._quote_context.candlesticks(
                    longbridge_symbol,
                    period,
                    request_count,
                    adjust_type,
                    TradeSessions.Intraday,
                )
            else:
                raw_bars = self._quote_context.history_candlesticks_by_offset(
                    longbridge_symbol,
                    period,
                    adjust_type,
                    False,
                    request_count,
                    as_of,
                    TradeSessions.Intraday,
                )
        except OpenApiException as exc:
            raise MarketDataProviderError(
                f"Longbridge bar request failed: code={exc.code}, message={exc.message}"
            ) from exc
        received_at = datetime.now(timezone.utc)

        bars = [
            map_longbridge_bar(
                raw_bar,
                symbol=symbol.strip().upper(),
                timeframe=timeframe,
                adjustment=normalized_adjustment,
                received_at=received_at,
                as_of=as_of,
            )
            for raw_bar in raw_bars
        ]
        bars = [
            bar
            for bar in bars
            if bar.start_at <= as_of
            and (bar.is_complete or include_incomplete)
        ]
        bars.sort(key=lambda bar: bar.start_at)
        return bars[-limit:]

    def get_intraday_bars(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        as_of: datetime,
    ) -> list[IntradayBar]:
        """按指定时间区间获取已完成的历史 1m K 线。"""

        request = HistoricalMinuteBarsRequest(
            symbol=symbol,
            start_at=start_at,
            end_at=end_at,
            as_of=as_of,
        )

        longbridge_symbol = to_longbridge_symbol(request.symbol)
        PAGE_SIZE = 1000
        MAX_PAGES = 12
        # 从查询窗口终点开始，逐步向历史方向移动。
        cursor = request.end_at
        collected: dict[datetime, IntradayBar] = {}

        for _ in range(MAX_PAGES):
            try:
                bars = self._quote_context.history_candlesticks_by_offset(
                    longbridge_symbol,
                    Period.Min_1,
                    AdjustType.NoAdjust,
                    False,
                    PAGE_SIZE,
                    cursor,
                    TradeSessions.All,
                )
            except OpenApiException as exc:
                raise MarketDataProviderError(
                    "Longbridge minute history request failed: "
                    f"code={exc.code}"
                ) from exc

            if not bars:
                break

            received_at = datetime.now(timezone.utc)
            page = [
                    map_longbridge_intraday_bar(
                        bar,
                        symbol=request.symbol.upper(),
                        received_at=received_at,
                        as_of=request.as_of,
                    )
                    for bar in bars
                ]
            oldest = min(bar.start_at for bar in page)

            # 只收集完整落在目标区间内的历史 K 线。
            for bar in page:

                if not (
                    request.start_at <= bar.start_at
                    and bar.end_at <= request.end_at
                    and bar.is_complete
                    and bar.end_at <= request.as_of
                ):
                    continue
                previous = collected.get(bar.start_at)

                if previous is not None:
                    # 分页边界允许重复返回同一根 K 线，
                    # 但不允许同一时间的数据互相矛盾。
                    previous_data = previous.model_dump(exclude={"received_at"})
                    current_data = bar.model_dump(exclude={"received_at"})
                    if previous_data != current_data:
                        raise MarketDataProviderError("Conflicting minute bars ""at the same timestamp")

                collected[bar.start_at] = bar

            # 已经覆盖到请求起点，无需继续分页。
            if oldest <= request.start_at:
                break

            # 游标没有向前推进，防止无限循环。
            if oldest >= cursor:
                raise MarketDataProviderError("Historical minute pagination made no progress")

            cursor = oldest
        else:
            raise MarketDataProviderError(
                "Historical minute pagination "
                "exceeded the configured page limit"
            )
        return [collected[key] for key in sorted(collected)]
