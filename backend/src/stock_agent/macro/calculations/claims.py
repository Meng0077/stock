from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import cast, Protocol

from stock_agent.macro.models.metric import EconomicIndicator, MacroMetricSnapshot


class WeeklyClaimsPoint(Protocol):
    """周频失业金计算所需的最小数据结构。"""

    week_ending: date
    value: int


@dataclass(frozen=True)
class WeeklyClaimsReading:
    """某项失业金指标的最新值与周变化。"""

    indicator: str
    period_end: date
    actual: int
    previous: int | None
    change: int | None


def calculate_weekly_claims(
    *,
    indicator: str,
    points: Sequence[WeeklyClaimsPoint],
) -> WeeklyClaimsReading | None:
    """计算某项周频指标的最新值、前值及周变化。

    previous 必须对应前一统计周。
    不用更早的记录冒充上周数据。
    """

    if not points:
        return None

    values = {point.week_ending: point.value for point in points}
    current_week = max(values)
    previous = values.get(current_week - timedelta(days=7))
    actual = values[current_week]

    return WeeklyClaimsReading(
        indicator=indicator,
        period_end=current_week,
        actual=actual,
        previous=previous,
        change=actual - previous if previous is not None else None,
    )


def weekly_claims_to_snapshot(
    reading: WeeklyClaimsReading,
    *,
    release_date: date | None = None,
) -> MacroMetricSnapshot:
    """把周频 Claims 数据转换为统一宏观指标。

    actual/previous 单位均为人数。
    change 当前不直接进入统一 Snapshot，
    因为 previous 已经足以计算变化。
    """

    return MacroMetricSnapshot(
        indicator=cast(EconomicIndicator, reading.indicator),
        measure="level",
        unit="persons",
        period=reading.period_end,
        actual=Decimal(reading.actual),
        previous=(
            Decimal(reading.previous)
            if reading.previous is not None
            else None
        ),
        release_date=release_date,
        source="fred_dol",
    )
