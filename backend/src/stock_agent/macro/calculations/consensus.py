
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from stock_agent.macro.models.metric import (
    ConsensusObservation,
    EconomicIndicator,
    EconomicMeasure,
    MacroMetricSnapshot,
)

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ConsensusMatch:
    """匹配到的预期及其历史时间验证状态。"""

    forecast: ConsensusObservation
    pit_verified: bool


def find_release_consensus(
    *,
    forecasts: list[ConsensusObservation],
    indicator: EconomicIndicator,
    measure: EconomicMeasure,
    period: date,
    release_date: date | None,
    released_at: datetime | None,
) -> ConsensusMatch | None:
    """查找某一次宏观发布对应的市场一致预期。

    先匹配指标、口径、统计期和美国东部发布日期。

    优先选择有可靠公布前历史时间戳的预期；
    否则仅当未验证预期恰好只有一条时，
    才允许普通在线研究使用它。

    多条无法区分的预期不任意选择。
    """

    if release_date is None:
        return None

    candidates = [
        item
        for item in forecasts
        if (
            item.indicator == indicator
            and item.measure == measure
            and item.period == period
            and item.scheduled_release_at.tzinfo is not None
            and item.scheduled_release_at.astimezone(
                EASTERN
            ).date() == release_date
        )
    ]

    # 有明确的真实发布时间时，
    # 才可能验证 forecast 是否为公布前版本。
    if released_at is not None:
        verified = [
            item
            for item in candidates
            if (
                item.forecast_as_of is not None
                and item.forecast_as_of.tzinfo is not None
                and item.forecast_as_of < released_at
            )
        ]

        if verified:
            latest_time = max(
                item.forecast_as_of
                for item in verified
                if item.forecast_as_of is not None
            )

            latest = [
                item
                for item in verified
                if item.forecast_as_of == latest_time
            ]

            # 同一时间存在冲突记录时，不猜测。
            if len(latest) != 1:
                return None

            return ConsensusMatch(
                forecast=latest[0],
                pit_verified=True,
            )

    # 普通 Calendar 没有历史 forecast 时间戳。
    # 只能作为未经 PIT 验证的参考预期。
    unverified = [
        item
        for item in candidates
        if item.forecast_as_of is None
    ]

    if len(unverified) != 1:
        return None

    return ConsensusMatch(
        forecast=unverified[0],
        pit_verified=False,
    )


def merge_consensus(
    *,
    metrics: list[MacroMetricSnapshot],
    forecasts: list[ConsensusObservation],
) -> list[MacroMetricSnapshot]:
    """给已计算完成的指标合并市场一致预期。

    输入：
        metrics：实际值及前值已经计算完成的指标。
        forecasts：TE 返回的候选预期。

    输出：
        合并 Consensus 和可选 Surprise 后的新指标列表。

    不修改原始指标，也不将估算 Surprise
    冒充严格 PIT 验证数据。
    """

    results = []
    for metric in metrics:
        match = find_release_consensus(
            forecasts=forecasts,
            indicator=metric.indicator,
            measure=metric.measure,
            period=metric.period,
            release_date=metric.release_date,
            released_at=metric.released_at,
        )
        if match is None:
            results.append(metric)
            continue

        forecast = match.forecast

        # 单位必须一致。
        # 百分比指标按本项目当前的一位小数口径比较；
        # 人数指标保留整数。
        precision = (
            Decimal("0.1")
            if metric.unit == "percent"
            else Decimal("1")
        )

        comparable_actual = metric.actual.quantize(
            precision,
            rounding=ROUND_HALF_UP,
        )

        surprise = (
            comparable_actual - forecast.consensus
            if match.pit_verified
            else None
        )

        results.append(
            metric.model_copy(
                update={
                    "consensus": forecast.consensus,
                    "surprise": surprise,
                    "forecast_as_of": forecast.forecast_as_of,
                    "consensus_pit_verified": match.pit_verified,
                    "surprise_is_estimated": (
                        match.pit_verified
                        and metric.actual_pit_status != "verified"
                    ),
                }
            )
        )
    return results
