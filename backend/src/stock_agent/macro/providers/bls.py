from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from stock_agent.macro.errors import MacroDataProviderError


BLS_API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


@dataclass(frozen=True)
class BLSSeriesPoint:
    """BLS 某个统计月份的一条原始指数记录。

    这里只保存官方 API 实际提供的字段。
    发布时间会在后续发布日历层补充。
    """

    series_id: str
    period: date
    value: Decimal


class BLSProvider:
    """通过 BLS 官方 API 获取真实经济数据。

    第一版使用无需 API Key 的 v1 接口。
    该类只负责网络请求和原始数据转换。
    """

    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch_series(
        self,
        series_ids: list[str],
    ) -> dict[str, list[BLSSeriesPoint]]:
        """批量获取指定 BLS 序列的最近历史数据。"""

        try:
            response = self.client.post(
                BLS_API_URL,
                json={"seriesid": series_ids},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MacroDataProviderError("BLS API request failed") from exc

        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise MacroDataProviderError(
                f"BLS API error: {payload.get('message')}"
            )

        result: dict[str, list[BLSSeriesPoint]] = {}

        for series in payload["Results"]["series"]:
            series_id = series["seriesID"]
            points = []

            for item in series["data"]:
                period = item["period"]

                # 仅使用 M01～M12 月度记录。
                # M13 等年度汇总不参与月度计算。
                if (
                    len(period) != 3
                    or not period.startswith("M")
                    or not period[1:].isdigit()
                    or not 1 <= int(period[1:]) <= 12
                ):
                    continue

                raw_value = str(item.get("value", "")).strip()
                if not raw_value or raw_value == "-":
                    continue

                points.append(
                    BLSSeriesPoint(
                        series_id=series_id,
                        period=date(
                            int(item["year"]),
                            int(period[1:]),
                            1,
                        ),
                        value=Decimal(item["value"]),
                    )
                )

            result[series_id] = sorted(
                points,
                key=lambda point: point.period,
            )

        return result
