from datetime import datetime
from typing import Protocol

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
