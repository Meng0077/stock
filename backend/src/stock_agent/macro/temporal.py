from datetime import datetime

from stock_agent.macro.models.metric import (
    MacroMetricSnapshot,
    TemporalValidation,
)


def validate_metric_as_of(
    metric: MacroMetricSnapshot,
    *,
    as_of: datetime,
    strict_pit: bool,
) -> TemporalValidation:
    """判断某项经济指标在 as_of 时是否允许使用。

    输入：
        metric:
            已构建好的宏观指标。

        as_of:
            本次研究的信息截止时间。

        strict_pit:
            True：
                用于历史回测/严格历史研究。

            False：
                用于最新市场研究，可以接受
                某些历史版本无法验证的数据。

    输出：
        TemporalValidation。

    注意：
        period 只是统计期，不能单独用于判断
        数据是否已经发布。
    """

    # ---------- 1. 明确的未来发布时间 ----------

    if (
        metric.released_at is not None
        and metric.released_at > as_of
    ):
        return TemporalValidation(
            decision="reject",
            reason="released_after_as_of",
        )

    # 只有日期，没有具体时间时，只做日期级判断。
    if (
        metric.released_at is None
        and metric.release_date is not None
        and metric.release_date > as_of.date()
    ):
        return TemporalValidation(
            decision="reject",
            reason="release_date_after_as_of",
        )

    # ---------- 2. 严格 PIT 模式 ----------

    if strict_pit:
        if metric.actual_pit_status == "verified":
            return TemporalValidation(
                decision="usable",
                reason="pit_verified",
            )

        if metric.actual_pit_status == "date_verified":
            # FRED realtime 查询只能保证日期级版本。
            # 如果系统需要日内严格回测，
            # 仍不能认为它完全可靠。
            return TemporalValidation(
                decision="usable_with_warning",
                reason="pit_verified_at_date_precision_only",
            )

        return TemporalValidation(
            decision="reject",
            reason="actual_pit_unverified",
        )

    # ---------- 3. 普通最新研究 ----------

    if metric.actual_pit_status == "unverified":
        return TemporalValidation(
            decision="usable_with_warning",
            reason="historical_revision_not_verified",
        )

    return TemporalValidation(
        decision="usable",
        reason="available",
    )

def validate_consensus(
    metric: MacroMetricSnapshot,
    *,
    strict_pit: bool,
) -> TemporalValidation:
    """检查 Consensus 是否适合计算 Surprise。"""

    if metric.consensus is None:
        return TemporalValidation(
            decision="usable",
            reason="consensus_missing",
        )

    if metric.consensus_pit_verified:
        return TemporalValidation(
            decision="usable",
            reason="consensus_pit_verified",
        )

    if strict_pit:
        return TemporalValidation(
            decision="reject",
            reason="consensus_pit_unverified",
        )

    return TemporalValidation(
        decision="usable_with_warning",
        reason="consensus_pit_unverified",
    )

def filter_metrics_as_of(
    metrics: list[MacroMetricSnapshot],
    *,
    as_of: datetime,
    strict_pit: bool,
) -> tuple[
    list[MacroMetricSnapshot],
    list[str],
]:
    """过滤不能在 as_of 使用的宏观指标。

    返回：
        usable_metrics
        warnings
    """

    usable = []
    warnings = []

    for metric in metrics:
        validation = validate_metric_as_of(
            metric,
            as_of=as_of,
            strict_pit=strict_pit,
        )

        if validation.decision == "reject":
            warnings.append(
                f"{metric.indicator}:"
                f"{metric.measure}:"
                f"{validation.reason}"
            )
            continue

        usable.append(metric)

        if (
            validation.decision
            == "usable_with_warning"
        ):
            warnings.append(
                f"{metric.indicator}:"
                f"{metric.measure}:"
                f"{validation.reason}"
            )

    return usable, warnings
