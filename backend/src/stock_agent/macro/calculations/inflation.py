from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, cast

from stock_agent.macro.calculations.consensus import find_release_consensus
from stock_agent.macro.calculations.series import (
    SeriesPoint,
    calculate_index_change,
    shift_month,
)
from stock_agent.macro.models.metric import (
    ConsensusObservation,
    EconomicMeasure,
    MacroMetricSnapshot,
)


@dataclass(frozen=True)
class InflationReading:
    """某个统计月份的通胀变化率及前值。

    所有数值均以百分比表示。
    """

    period: date
    mom_actual_pct: Decimal
    mom_previous_pct: Decimal | None
    yoy_actual_pct: Decimal
    yoy_previous_pct: Decimal | None


InflationIndicator = Literal[
    "cpi",
    "core_cpi",
    "ppi",
    "core_ppi",
    "pce",
    "core_pce",
]


def calculate_inflation_reading(
    *,
    sa_points: Sequence[SeriesPoint],
    nsa_points: Sequence[SeriesPoint],
) -> InflationReading | None:
    """计算最新可用月份的实际 MoM、YoY 及各自前值。"""

    sa = {point.period: point.value for point in sa_points}
    nsa = {point.period: point.value for point in nsa_points}

    for current in sorted(set(sa) & set(nsa), reverse=True):
        mom = calculate_index_change(
            sa,
            current=current,
            previous=shift_month(current, -1),
        )
        yoy = calculate_index_change(
            nsa,
            current=current,
            previous=shift_month(current, -12),
        )

        if mom is None or yoy is None:
            continue

        previous = shift_month(current, -1)
        return InflationReading(
            period=current,
            mom_actual_pct=mom,
            mom_previous_pct=calculate_index_change(
                sa,
                current=previous,
                previous=shift_month(current, -2),
            ),
            yoy_actual_pct=yoy,
            yoy_previous_pct=calculate_index_change(
                nsa,
                current=previous,
                previous=shift_month(current, -13),
            ),
        )

    return None


def calculate_pce_reading(
    points: Sequence[SeriesPoint],
) -> InflationReading | None:
    """计算 PCE 或 Core PCE 的实际变化率及前值。

    输入：
        同一条 BEA 经季调月度价格指数序列。

    输出：
        最新可计算月份的 MoM、YoY，
        以及上一个月对应的 MoM、YoY。

    不负责：
        API 请求、Consensus、Surprise、
        发布时间和历史修订版本管理。
    """

    values = {point.period: point.value for point in points}

    # 找到最新一个具备完整计算条件的月份。
    for current in sorted(values, reverse=True):
        previous_month = shift_month(current, -1)
        mom = calculate_index_change(
            values,
            current=current,
            previous=previous_month,
        )
        yoy = calculate_index_change(
            values,
            current=current,
            previous=shift_month(current, -12),
        )

        if mom is None or yoy is None:
            continue

        return InflationReading(
            period=current,
            mom_actual_pct=mom,
            mom_previous_pct=calculate_index_change(
                values,
                current=previous_month,
                previous=shift_month(current, -2),
            ),
            yoy_actual_pct=yoy,
            yoy_previous_pct=calculate_index_change(
                values,
                current=previous_month,
                previous=shift_month(current, -13),
            ),
        )

    return None


def build_inflation_metrics(
    *,
    indicator: InflationIndicator,
    reading: InflationReading,
    forecasts: list[ConsensusObservation],
    release_date: date | None,
    released_at: datetime | None = None,
    source: str = "bls",
) -> dict[str, MacroMetricSnapshot]:
    """合并通胀数据、发布日期与可选市场预期。

    当前 BLS / BEA API 返回值可能包含后续修订，因此即使已经
    取得发布日期，``actual_pit_status`` 仍保持 ``unverified``。
    """

    values = {
        "mom": (reading.mom_actual_pct, reading.mom_previous_pct),
        "yoy": (reading.yoy_actual_pct, reading.yoy_previous_pct),
    }
    results: dict[str, MacroMetricSnapshot] = {}

    for measure, (actual, previous) in values.items():
        match = find_release_consensus(
            forecasts=forecasts,
            indicator=indicator,
            measure=cast(EconomicMeasure, measure),
            period=reading.period,
            release_date=release_date,
            released_at=released_at,
        )

        forecast = match.forecast if match is not None else None

        consensus_pit_verified = (
            match.pit_verified if match is not None else False
        )

        consensus = forecast.consensus if forecast is not None else None
        surprise = None

        if consensus is not None and consensus_pit_verified:
            # CPI/PPI/PCE 百分比 headline 暂按一位小数比较。
            # 指数计算结果不等同于官方公布初值，
            # 因此 Surprise 仍属于估算值。
            comparable_actual = actual.quantize(
                Decimal("0.1"),
                rounding=ROUND_HALF_UP,
            )
            surprise = comparable_actual - consensus

        results[measure] = MacroMetricSnapshot(
            indicator=indicator,
            measure=cast(Literal["mom", "yoy"], measure),
            unit="percent",
            period=reading.period,
            actual=actual,
            previous=previous,
            consensus=consensus,
            surprise=surprise,
            release_date=release_date,
            released_at=released_at,
            forecast_as_of=(
                forecast.forecast_as_of
                if forecast is not None
                else None
            ),
            consensus_pit_verified=consensus_pit_verified,
            surprise_is_estimated=True,
            source=source,
            actual_pit_status="unverified",
        )

    return results
