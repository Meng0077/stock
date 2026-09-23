from datetime import datetime

from stock_agent.market.schemas import (
    Bar,
    BarTimeframe,
    Quote,
)

class FixtureMarketDataProvider:
    """基于本地固定数据实现行情 Provider。

    主要用途：
        - 离线开发；
        - 自动化测试；
        - 不依赖真实行情 API；
        - 保证相同输入得到相同结果。

    Args:
        quotes:
            按 symbol 保存的报价数据。
            例如：
                {
                    "NVDA": Quote(...),
                    "AMD": Quote(...),
                }

        bars:
            按 (symbol, timeframe) 保存的历史 K 线。
            例如：
                {
                    ("NVDA", "1d"): [...],
                    ("AMD", "1d"): [...],
                }

    不负责：
        - 解析“英伟达”这种自然语言公司名；
        - 请求外部行情服务；
        - 计算技术指标；
        - 生成投资结论。
    """

    def __init__(
        self,
        *,
        quotes: dict[str, Quote],
        bars: dict[
            tuple[str, BarTimeframe],
            list[Bar],
        ],
    ) -> None:
        """保存构造时注入的 Fixture 数据。

        Fixture 数据由调用方准备，
        Provider 本身只负责查询和 point-in-time 过滤。
        """

        self._quotes = quotes
        self._bars = bars

    def get_quote(
        self,
        symbol: str,
        *,
        as_of: datetime,
    ) -> Quote | None:
        """获取 as_of 时点已经可用的 Fixture 报价。

        Args:
            symbol:
                标准证券代码，例如 "NVDA"。

            as_of:
                当前请求允许看到数据的最晚时间。

        Returns:
            找到且已经在 as_of 前产生的 Quote。

            如果 symbol 不存在，
            或报价时间晚于 as_of，
            返回 None。
        注意：
        quoted_at 表示市场报价发生时间；
        received_at 表示系统真正拿到该报价的时间。

        Point-in-time 判断应该使用 received_at，
        避免系统提前看到尚未收到的数据。
        """
        normalized_symbol = symbol.strip().upper()
        quote = self._quotes.get(normalized_symbol)

        if quote is None or quote.received_at > as_of:
            return None
        return quote

    def get_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        timeframe: BarTimeframe,
        limit: int,
        include_incomplete: bool = False,
    ) -> list[Bar]:
        """获取截至 as_of 已完成的历史 K 线。

        Args:
            symbol:
                标准证券代码。

            as_of:
                当前请求允许看到信息的最大时间。

            timeframe:
                K 线周期，例如 "1d"。

            limit:
                最多返回多少根 K 线。

        Returns:
            按时间从旧到新排列的 Bar。

            只返回：
                - is_complete == True。
                - updated_at <= as_of。

        Raises:
            ValueError:
                limit <= 0。
        """
        if limit <= 0:
            raise ValueError(
                "limit must be greater than 0"
            )


        normalized_symbol = symbol.strip().upper()
        bars = self._bars.get((normalized_symbol, timeframe), [])
        available_bars = [
            bar
            for bar in bars
            if bar.updated_at <= as_of
            and (bar.is_complete or include_incomplete)
        ]

        available_bars.sort(key=lambda bar: bar.start_at)

        return available_bars[-limit:]
