from datetime import datetime
from zoneinfo import ZoneInfo

from stock_agent.macro.models.metric import (
    MacroMetricSnapshot,
    TemporalValidation,
)
from stock_agent.macro.models.release import MacroReleaseEvent


EASTERN = ZoneInfo("America/New_York")


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

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    research_date = as_of.astimezone(EASTERN).date()

    # ---------- 1. 明确的未来发布时间 ----------

    if (
        metric.released_at is not None
        and (
            metric.released_at.tzinfo is None
            or metric.released_at.utcoffset() is None
        )
    ):
        return TemporalValidation(
            decision="reject",
            reason="invalid_release_timestamp",
        )

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
        and metric.release_date > research_date
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


def validate_release_as_of(
    release: MacroReleaseEvent,
    *,
    as_of: datetime,
    strict_pit: bool = False,
) -> TemporalValidation:
    """检查一次宏观发布是否允许进入当前研究。

    普通研究：
        已确认 released_at 的事件按精确时间判断；
        只有 release_date 的事件保守地等到下一天。

    严格 PIT：
        还要求事件与统计期的绑定已经验证。
        单项 actual 的历史版本另行检查。
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    research_date = as_of.astimezone(EASTERN).date()

    # 1. 已取得经核实的实际发布时间。
    if release.released_at is not None:
        released_at = release.released_at

        if (
            released_at.tzinfo is None
            or released_at.utcoffset() is None
        ):
            return TemporalValidation(
                decision="reject",
                reason="invalid_release_timestamp",
            )

        if released_at > as_of:
            return TemporalValidation(
                decision="reject",
                reason="release_not_yet_published",
            )

        if released_at.astimezone(EASTERN).date() != (
            release.release_date
        ):
            return TemporalValidation(
                decision="reject",
                reason="release_date_time_conflict",
            )

    # 2. 只有发布日期，没有实际发布时间。
    else:
        if release.release_date >= research_date:
            return TemporalValidation(
                decision="reject",
                reason="exact_release_time_unverified",
            )

        if strict_pit:
            return TemporalValidation(
                decision="reject",
                reason="exact_release_time_missing",
            )

    # 3. 严格 PIT 需要验证事件和统计期的对应关系。
    if (
        strict_pit
        and release.period_binding != "verified"
    ):
        return TemporalValidation(
            decision="reject",
            reason="release_period_binding_unverified",
        )

    # 4. 普通在线研究允许保留未严格验证的事件。
    if release.period_binding != "verified":
        return TemporalValidation(
            decision="usable_with_warning",
            reason="release_period_binding_unverified",
        )

    return TemporalValidation(
        decision="usable",
        reason="release_available",
    )


def filter_releases_as_of(
    releases: list[MacroReleaseEvent],
    *,
    as_of: datetime,
    strict_pit: bool = False,
) -> tuple[list[MacroReleaseEvent], list[str]]:
    """过滤尚不可用的发布事件及其指标。

    返回：
        usable_releases
        warnings
    """

    usable_releases = []
    warnings = []

    for release in releases:
        validation = validate_release_as_of(
            release,
            as_of=as_of,
            strict_pit=strict_pit,
        )

        if validation.decision == "reject":
            warnings.append(
                f"{release.release_id}:{validation.reason}"
            )
            continue

        if validation.decision == "usable_with_warning":
            warnings.append(
                f"{release.release_id}:{validation.reason}"
            )

        # 复用已有的指标级时间检查。
        usable_metrics, metric_warnings = filter_metrics_as_of(
            release.metrics,
            as_of=as_of,
            strict_pit=strict_pit,
        )

        warnings.extend(
            f"{release.release_id}:{warning}"
            for warning in metric_warnings
        )

        if not usable_metrics:
            warnings.append(
                f"{release.release_id}:no_usable_metrics"
            )
            continue

        usable_releases.append(
            release.model_copy(
                update={"metrics": usable_metrics}
            )
        )

    return usable_releases, warnings
