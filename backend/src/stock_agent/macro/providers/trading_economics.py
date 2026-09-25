from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import cast

import httpx

from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.models.metric import (
    ConsensusObservation,
    EconomicIndicator,
    EconomicMeasure,
)


# 供应商字段到系统内部字段的映射。
EVENT_MAPPING = {
    "Inflation Rate MoM": ("cpi", "mom"),
    "Inflation Rate YoY": ("cpi", "yoy"),
    "Core Inflation Rate MoM": ("core_cpi", "mom"),
    "Core Inflation Rate YoY": ("core_cpi", "yoy"),
    "PPI MoM": ("ppi", "mom"),
    "PPI YoY": ("ppi", "yoy"),
    "Core PPI MoM": ("core_ppi", "mom"),
    "Core PPI YoY": ("core_ppi", "yoy"),
}


def parse_percent(value: str) -> Decimal | None:
    """将供应商的百分比字符串转换成 Decimal。"""

    raw = value.strip().removesuffix("%").strip()
    if raw in {"", "-"}:
        return None

    try:
        result = Decimal(raw)
    except InvalidOperation:
        return None

    return result if result.is_finite() else None


class TradingEconomicsConsensusProvider:
    """从真实经济日历获取美国通胀指标的预期数据。

    当前只支持查询日历快照，不承诺能够恢复
    历史上任意 as_of 时刻的市场预期。
    """

    def __init__(self, client: httpx.Client, api_key: str):
        self.client = client
        self.api_key = api_key

    def get_consensus(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[ConsensusObservation]:
        url = (
            "https://api.tradingeconomics.com/calendar/country/"
            f"united%20states/{start_date.isoformat()}/{end_date.isoformat()}"
        )

        try:
            response = self.client.get(
                url,
                params={"c": self.api_key},
            )
            response.raise_for_status()
            events = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MacroDataProviderError(
                "Failed to fetch economic calendar"
            ) from exc

        if not isinstance(events, list):
            raise MacroDataProviderError("Unexpected calendar response")

        observations = []
        for event in events:
            if event.get("Country") != "United States":
                continue

            mapping = EVENT_MAPPING.get(event.get("Event"))
            if mapping is None:
                continue

            # 只接受有确定公布时间的日历事件。
            if str(event.get("DateSpan")) != "0":
                continue

            consensus = parse_percent(str(event.get("Forecast") or ""))
            if consensus is None:
                continue

            reference = datetime.fromisoformat(event["ReferenceDate"]).date()
            release_at = datetime.fromisoformat(
                event["Date"].replace("Z", "+00:00")
            )
            if release_at.tzinfo is None:
                release_at = release_at.replace(tzinfo=timezone.utc)

            indicator, measure = mapping
            observations.append(
                ConsensusObservation(
                    indicator=cast(EconomicIndicator, indicator),
                    measure=cast(EconomicMeasure, measure),
                    period=reference.replace(day=1),
                    scheduled_release_at=release_at,
                    consensus=consensus,
                    source="trading_economics",
                    event_id=str(event["CalendarId"]),
                    # 普通 Calendar 响应不能证明预测属于哪个历史快照。
                    forecast_as_of=None,
                )
            )

        return observations
