from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast

from stock_agent.macro.calculations.series import (
    SeriesPoint,
    calculate_index_change,
    shift_month,
)
from stock_agent.macro.models.metric import (
    EconomicIndicator,
    EconomicMeasure,
    EconomicUnit,
    MacroMetricSnapshot,
)


@dataclass(frozen=True)
class EmploymentMetric:
    """某个就业指标的最新实际值及其前值。

    actual 和 previous 使用 unit 指定的单位。
    previous 表示相同 measure 的上一统计期数值。
    不包含 consensus 和 surprise。
    """

    indicator: EconomicIndicator
    measure: EconomicMeasure
    period: date
    actual: Decimal
    previous: Decimal | None
    unit: EconomicUnit


def calculate_nonfarm_payrolls(
    points: Sequence[SeriesPoint],
) -> EmploymentMetric | None:
    """由非农就业总人数计算本月及上月新增岗位。

    输入：同一条经季调非农就业人数序列。
    输出：最新月度新增岗位及上一月新增岗位。
    不负责：获取数据、预测和修订版本管理。
    """

    levels = {point.period: point.value for point in points}
    if not levels:
        return None

    current = max(levels)
    previous_month = shift_month(current, -1)
    two_months_ago = shift_month(current, -2)
    if previous_month not in levels:
        return None

    return EmploymentMetric(
        indicator="nonfarm_payrolls",
        measure="monthly_change",
        period=current,
        actual=(levels[current] - levels[previous_month]) * Decimal("1000"),
        previous=(
            (levels[previous_month] - levels[two_months_ago])
            * Decimal("1000")
            if two_months_ago in levels
            else None
        ),
        unit="jobs",
    )


def calculate_unemployment_rate(
    points: Sequence[SeriesPoint],
) -> EmploymentMetric | None:
    """获取最新失业率及上个月的失业率。"""

    rates = {point.period: point.value for point in points}
    if not rates:
        return None

    current = max(rates)
    return EmploymentMetric(
        indicator="unemployment_rate",
        measure="monthly_change",
        period=current,
        actual=rates[current],
        previous=rates.get(shift_month(current, -1)),
        unit="percent",
    )


def calculate_average_hourly_earnings(
    points: Sequence[SeriesPoint],
) -> list[EmploymentMetric]:
    """平均时薪的水平、MoM 与 YoY。"""

    earnings = {point.period: point.value for point in points}
    if not earnings:
        return []

    current = max(earnings)
    previous_month = shift_month(current, -1)
    results = [
        EmploymentMetric(
            indicator="average_hourly_earnings",
            measure="level",
            period=current,
            actual=earnings[current],
            previous=earnings.get(previous_month),
            unit="usd_per_hour",
        )
    ]

    for measure, months in (("mom", 1), ("yoy", 12)):
        actual = calculate_index_change(
            earnings,
            current=current,
            previous=previous_month,
        )
        if actual is None:
            continue

        previous = calculate_index_change(
            earnings,
            current=previous_month,
            previous=shift_month(previous_month, -months),
        )
        results.append(
            EmploymentMetric(
                indicator="average_hourly_earnings",
                measure=cast(EconomicMeasure, measure),
                period=current,
                actual=actual,
                previous=previous,
                unit="percent",
            )
        )

    return results


def employment_metric_to_snapshot(
    metric: EmploymentMetric,
    *,
    release_date: date | None = None,
) -> MacroMetricSnapshot:
    """将就业模块内部计算结果转换为统一宏观指标。

    这里只负责结构转换。
    不计算 Consensus 和 Surprise。
    """

    return MacroMetricSnapshot(
        indicator=metric.indicator,
        measure=metric.measure,
        unit=metric.unit,
        period=metric.period,
        actual=metric.actual,
        previous=metric.previous,
        release_date=release_date,
        source="bls",
    )
