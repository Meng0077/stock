import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

import httpx

from stock_agent.macro.errors import MacroDataProviderError


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

CLAIMS_SERIES = {
    "initial_claims": "ICSA",
    "continuing_claims": "CCSA",
    "initial_claims_4w_avg": "IC4WSA",
}


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
    """从 FRED 获取美国劳工部的真实周频失业金数据。

    第一版只负责当前最新数据及近期历史，
    不承诺支持任意 as_of 的严格历史回放。
    """

    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch_series(
        self,
        series_id: str,
        *,
        start_date: date,
    ) -> list[WeeklyClaimsPoint]:
        """获取某条周频序列，并按统计周升序返回。"""

        try:
            response = self.client.get(
                FRED_CSV_URL,
                params={
                    "id": series_id,
                    "cosd": start_date.isoformat(),
                },
            )
            response.raise_for_status()
            reader = csv.reader(StringIO(response.text))
            header = next(reader)

            if len(header) != 2 or header[1] != series_id:
                raise MacroDataProviderError(
                    "Unexpected FRED CSV header"
                )

            points = []
            for row in reader:
                if len(row) != 2:
                    raise MacroDataProviderError("Invalid FRED CSV row")

                raw_date, raw_value = row

                # 缺失值不能当成零。
                if raw_value.strip() in {"", "."}:
                    continue

                number = Decimal(raw_value)
                if (
                    not number.is_finite()
                    or number < 0
                    or number != number.to_integral_value()
                ):
                    raise MacroDataProviderError("Invalid claims value")

                points.append(
                    WeeklyClaimsPoint(
                        series_id=series_id,
                        week_ending=date.fromisoformat(raw_date),
                        value=int(number),
                    )
                )

            return sorted(points, key=lambda point: point.week_ending)
        except (
            httpx.HTTPError,
            ValueError,
            InvalidOperation,
            csv.Error,
            StopIteration,
        ) as exc:
            raise MacroDataProviderError(
                f"Failed to fetch {series_id}"
            ) from exc
