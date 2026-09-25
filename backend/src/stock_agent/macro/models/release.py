from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from stock_agent.macro.models.metric import MacroMetricSnapshot


MacroReleaseType = Literal[
    "cpi",
    "ppi",
    "employment_situation",
    "pce",
    "weekly_claims",
]

ReleasePeriodBinding = Literal[
    "verified",
    "latest_assumed",
]


class MacroReleaseEvent(BaseModel):
    """一次完整的宏观经济数据发布事件。

    例如一次 CPI 发布会同时包含：
        - Headline CPI MoM
        - Headline CPI YoY
        - Core CPI MoM
        - Core CPI YoY

    release_date:
        官方发布日期。当前可由 FRED release/dates 获得。

    scheduled_release_at:
        日历中的计划发布时间。例如来自 Trading Economics。
        它不是官方实际发布时间。

    released_at:
        已确认的真实发布时间。当前无法可靠确认时保持 None。

    period_binding:
        当前 release_date 与 metrics 中统计期的对应关系
        是否已经严格验证。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    release_id: str
    release_type: MacroReleaseType
    release_date: date
    scheduled_release_at: datetime | None = None
    released_at: datetime | None = None
    release_date_source: str
    schedule_source: str | None = None
    period_binding: ReleasePeriodBinding
    metrics: list[MacroMetricSnapshot]
