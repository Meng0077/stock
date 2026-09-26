from dataclasses import dataclass
from datetime import date
from typing import Literal

from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.providers.fred import FredProvider


CLAIMS_SERIES = {
    "initial_claims": "ICSA",
    "continuing_claims": "CCSA",
    "initial_claims_4w_avg": "IC4WSA",
}

ClaimsIndicator = Literal[
    "initial_claims",
    "continuing_claims",
    "initial_claims_4w_avg",
]


@dataclass(frozen=True)
class WeeklyClaimsPoint:
    """一条周频失业金申领数据。

    series_id:
        FRED 序列编码。

    week_ending:
        数据对应的统计周结束日期。

    value:
        申领人数，单位为人。

    本模型只表示原始时间序列，
    不负责计算前值或预期差。
    """

    series_id: str
    week_ending: date
    value: int


class WeeklyClaimsProvider:
    """通过统一 FredProvider 获取周度失业金申领数据。"""

    def __init__(self, fred: FredProvider) -> None:
        self.fred = fred

    def fetch_series(
        self,
        series_id: str,
        *,
        start_date: date,
        as_of: date,
    ) -> list[WeeklyClaimsPoint]:
        """获取指定序列截至某个日期的近期历史。

        FRED vintage 只提供日期级历史版本，
        不能证明数据在 as_of 当天某一时刻已经公布。
        """

        if series_id not in CLAIMS_SERIES.values():
            raise ValueError(
                f"Unsupported claims series: {series_id}"
            )

        observations = self.fred.get_observations(
            series_id,
            observation_start=start_date,
            observation_end=as_of,
            realtime_start=as_of,
            realtime_end=as_of,
        )

        points = []
        for item in observations:
            if (
                item.value < 0
                or item.value != item.value.to_integral_value()
            ):
                raise MacroDataProviderError(
                    f"Invalid claims value for {series_id}"
                )
            points.append(
                WeeklyClaimsPoint(
                    series_id=series_id,
                    week_ending=item.period,
                    value=int(item.value),
                )
            )

        return sorted(points, key=lambda point: point.week_ending)
