from datetime import date, timedelta

from stock_agent.macro.models.treasury import (
    TreasuryTenor,
    TreasuryYield,
)
from stock_agent.macro.providers.fred import FredProvider


TREASURY_SERIES: dict[TreasuryTenor, str] = {
    "3m": "DGS3MO",
    "2y": "DGS2",
    "10y": "DGS10",
    "30y": "DGS30",
}


class TreasuryRatesProvider:
    """基于 FRED API 的美债收益率业务适配器。

    职责：
        将 FRED 原始观测转换为 TreasuryYield。

    不负责：
        通用 HTTP 请求、JSON 解析、
        收益率曲线组装、债券价格计算或交易判断。
    """

    def __init__(self, fred: FredProvider) -> None:
        self.fred = fred

    def get_yields(
        self,
        tenors: list[TreasuryTenor],
        *,
        as_of: date,
        lookback_days: int = 30,
    ) -> list[TreasuryYield]:
        """获取指定期限的近期日频收益率。

        输入：
            tenors：
                要获取的期限，例如 ["2y", "10y"]。

            as_of：
                查询截止日期，同时用作 FRED
                历史版本查询日期。

            lookback_days：
                向前获取多少个自然日的数据。

        输出：
            保留期限、统计日期、来源的观测记录。

        注意：
            当前只支持日期级别的历史查询。
            不代表某天盘中已经能够取得该数据。
        """

        if lookback_days < 1:
            raise ValueError("lookback_days must be positive")

        start = as_of - timedelta(days=lookback_days)
        results: list[TreasuryYield] = []

        for tenor in dict.fromkeys(tenors):
            series_id = TREASURY_SERIES[tenor]

            # 复用 FOMC 使用的通用 FRED Provider。
            # realtime_start/end 用于指定历史版本日期。
            points = self.fred.get_observations(
                series_id,
                observation_start=start,
                observation_end=as_of,
                realtime_start=as_of,
                realtime_end=as_of,
            )

            for point in points:
                results.append(
                    TreasuryYield(
                        observation_date=point.period,
                        tenor=tenor,
                        yield_pct=point.value,
                        released_at=None,
                        source="fred_h15",
                        source_url=(
                            "https://fred.stlouisfed.org/"
                            f"series/{series_id}"
                        ),
                    )
                )

        return results
