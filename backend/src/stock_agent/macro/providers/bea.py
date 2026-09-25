"""BEA 官方月度 PCE 价格指数适配器。"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re

import httpx

from stock_agent.macro.errors import MacroDataProviderError


BEA_API_URL = "https://apps.bea.gov/api/data"

PCE_SERIES = {
    "pce": "DPCERG",
    "core_pce": "DPCCRG",
}


@dataclass(frozen=True)
class BEAIndexPoint:
    """一条 BEA 月度价格指数记录。

    series_code:
        BEA 原始序列编码。

    period:
        统计月份，统一用该月第一天表示。

    value:
        价格指数水平，不是百分比增长率。
    """

    series_code: str
    period: date
    value: Decimal


class BEAPCEProvider:
    """获取 BEA 官方 PCE 和 Core PCE 月度指数。

    只负责 API 请求及供应商字段转换。
    不计算通胀率，不补造正式发布时间。
    """

    def __init__(self, client: httpx.Client, api_key: str):
        self.client = client
        self.api_key = api_key

    def fetch_indexes(
        self,
        *,
        years: list[int],
    ) -> dict[str, list[BEAIndexPoint]]:
        """获取指定年份的两条月度 PCE 指数序列。"""

        try:
            response = self.client.get(
                BEA_API_URL,
                params={
                    "UserID": self.api_key,
                    "method": "GetData",
                    "DataSetName": "NIPA",
                    "TableName": "T20804",
                    "Frequency": "M",
                    "Year": ",".join(str(year) for year in years),
                    "ResultFormat": "JSON",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MacroDataProviderError("BEA API request failed") from exc

        # BEA 即使返回 HTTP 200，也可能包含业务错误。
        api = payload.get("BEAAPI", {})
        results = api.get("Results", {})

        if not isinstance(results, dict):
            raise MacroDataProviderError("Unexpected BEA response")

        if "Error" in results:
            raise MacroDataProviderError(
                f"BEA API error: {results['Error']}"
            )

        rows = results.get("Data")
        if not isinstance(rows, list):
            raise MacroDataProviderError("BEA response has no Data list")

        series_mapping = {code: name for name, code in PCE_SERIES.items()}
        data: dict[str, list[BEAIndexPoint]] = {
            "pce": [],
            "core_pce": [],
        }

        for row in rows:
            series_code = row.get("SeriesCode")
            indicator = series_mapping.get(series_code)

            if indicator is None:
                continue

            # BEA 月度时间格式，例如 2026M7。
            match = re.fullmatch(
                r"(\d{4})M(0?[1-9]|1[0-2])",
                str(row.get("TimePeriod", "")),
            )
            if match is None:
                continue

            raw_value = (
                str(row.get("DataValue", ""))
                .strip()
                .replace(",", "")
            )
            if raw_value in {"", "-", "...", "(NA)", "N/A"}:
                continue

            try:
                value = Decimal(raw_value)
            except InvalidOperation as exc:
                raise MacroDataProviderError(
                    "Invalid BEA index value"
                ) from exc

            if not value.is_finite() or value <= 0:
                raise MacroDataProviderError("Invalid BEA price index")

            data[indicator].append(
                BEAIndexPoint(
                    series_code=series_code,
                    period=date(
                        int(match.group(1)),
                        int(match.group(2)),
                        1,
                    ),
                    value=value,
                )
            )

        for points in data.values():
            points.sort(key=lambda point: point.period)

        return data
