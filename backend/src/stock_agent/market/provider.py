from datetime import datetime
from typing import Protocol

from stock_agent.market.intraday import IntradayBar
from stock_agent.market.schemas import Bar, BarTimeframe, Quote


class MarketDataProvider(Protocol):
    """统一行情数据接口。

    不规定底层使用哪个行情服务商。
    """

    def get_quote(
        self,
        symbol: str,
        *,
        as_of: datetime,
    ) -> Quote | None:
        """获取指定 symbol 在 as_of 时点允许使用的最新报价。

        Args:
            symbol:
                标准股票代码，例如 "NVDA"。

            as_of:
                本次请求允许使用信息的最大时间。

                Provider 不能返回在 as_of 之后才产生的报价，
                防止 point-in-time 数据泄漏。

        Returns:
            Quote:
                找到可用报价。

            None:
                当前 Provider 没有该证券的可用报价。
        """
        ...

    def get_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        timeframe: BarTimeframe,
        limit: int,
        include_incomplete: bool = False,
    ) -> list[Bar]:
        """获取指定 symbol 的历史 K 线。

        Args:
            symbol:
                标准股票代码，例如 "NVDA"。

            as_of:
                本次请求允许使用信息的最大时间。

                返回的 Bar 必须是在该时点已经可用的数据。

            timeframe:
                K 线周期，例如 "1d"。

            limit:
                最多返回多少根 K 线。

        Returns:
            按时间从旧到新排列的 Bar 列表。

            没有数据时返回空列表，而不是 None。
        """
        ...

    def get_intraday_bars(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        as_of: datetime,
    ) -> list[IntradayBar]:
        """查询指定历史区间内的已完成分钟 K 线。

        时间区间采用 [start_at, end_at)。

        每根返回的 Bar 必须满足：
            start_at <= bar.start_at
            bar.end_at <= end_at
            bar.is_complete == True
            bar.end_at <= as_of

        返回值：
            按 start_at 升序排列的 IntradayBar。

            空列表表示 Provider 支持分钟历史查询，
            但指定区间内没有返回数据。

        Provider 不支持或未配置分钟行情时：
            抛出 MarketDataCapabilityError。

        数据源查询失败时：
            抛出 MarketDataProviderError。

        """
        ...
