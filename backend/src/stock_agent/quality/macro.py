
from pydantic import AwareDatetime, validate_call

from stock_agent.macro.models.release import MacroReleaseEvent, MacroReleaseType
from stock_agent.macro.models.snapshot import MacroSnapshot
from stock_agent.macro.temporal import (
    validate_release_as_of,
    validate_metric_as_of,
    validate_consensus,
)
from stock_agent.quality.models import (
    DataQualityResult,
    QualityIssue,
    QualityStatus,
)



@validate_call
def validate_macro_release(
    *,
    release: MacroReleaseEvent,
    as_of: AwareDatetime,
    strict_pit: bool = False,
) -> DataQualityResult:

    issues: list[QualityIssue] = []

    def make_result(
            status: QualityStatus,
        ) -> DataQualityResult:
            return DataQualityResult(
                data_kind="macro",
                target_id=release.release_id,
                purpose="macro_research",
                status=status,
                issues=issues,
                as_of=as_of,
            )

    # ---------- 1. 整次发布的时间校验 ----------
    release_validation = validate_release_as_of(release, as_of=as_of, strict_pit=strict_pit)
    if release_validation.decision == 'reject':
        issues.append(
            QualityIssue(
                code=release_validation.reason,
                message="宏观发布事件不满足时间有效性要求",
            )
        )
        return make_result("rejected")

    if release_validation.decision == 'usable_with_warning':
        issues.append(
            QualityIssue(
                code=release_validation.reason,
                message="宏观发布事件的历史时间证据不完整",
            )
        )

    # ---------- 2. 检查是否包含指标 ----------
    if not release.metrics:
        issues.append(
            QualityIssue(
                code="macro_metrics_missing",
                message="该次宏观发布没有可用指标",
            )
        )
        return make_result("rejected")

    # ---------- 3. 逐项检查 Actual 和 Forecast ----------
    usable_count = 0
    for metric in release.metrics:
        # actual
        actual_validation = validate_metric_as_of(metric, as_of=as_of, strict_pit=strict_pit)
        if actual_validation.decision == 'reject':
            issues.append(
                QualityIssue(
                    code=actual_validation.reason,
                    message="该指标的 Actual 不可用于本次研究",
                    details= { "indicator": metric.indicator, "measure": metric.measure,},
                )
            )
            continue
        usable_count += 1
        if actual_validation.decision == "usable_with_warning":
            issues.append(
                QualityIssue(
                    code=actual_validation.reason,
                    message="该指标的 Actual 历史版本未经完全验证",
                    details= { "indicator": metric.indicator, "measure": metric.measure,},
                )
            )

        # forecast
        if metric.consensus is None:
            continue
        consensus_validation = validate_consensus(metric, strict_pit=strict_pit)
        if consensus_validation.decision != "usable":
            issues.append(
                QualityIssue(
                    code=consensus_validation.reason,
                    message=(
                        "Forecast 的公布前历史版本未经验证；"
                        "严格 PIT 模式下不得使用该 Forecast"
                    ),
                    details= { "indicator": metric.indicator, "measure": metric.measure,},
                )
            )


    # ---------- 4. 综合判断 ----------

    if usable_count == 0:
        issues.append(
            QualityIssue(
                code="no_usable_macro_metrics",
                message="没有任何指标通过 Actual 时间校验",
            )
        )
        return make_result("rejected")


    if issues:
        return make_result("degraded")

    return make_result("usable")




def validate_macro_snapshot(
    *,
    snapshot: MacroSnapshot,
    strict_pit: bool = False,
) -> list[DataQualityResult]:
    """分别检查 Snapshot 中已经存在的宏观发布。"""

    return [
        validate_macro_release(
            release=release,
            as_of=snapshot.as_of,
            strict_pit=strict_pit,
        )
        for release in snapshot.recent_releases
    ]

def check_required_macro_releases(
    *,
    snapshot: MacroSnapshot,
    required_types: set[MacroReleaseType],
) -> list[DataQualityResult]:
    """检查本次研究要求的宏观发布是否存在。"""

    # 已经成功进入 Snapshot 的发布类型。
    available_types = [release.release_type for release in snapshot.recent_releases]
    results: list[DataQualityResult] = []

    for release_type in sorted(required_types):
        if release_type in available_types:
            continue

        results.append(DataQualityResult(
                data_kind="macro",
                target_id=f"{release_type}:latest",
                purpose="macro_research",
                status="rejected",
                issues=[
                    QualityIssue(
                        code="macro_release_missing",
                        message=(
                            f"截至研究截止时间，"
                            f"未取得可用的 {release_type} 发布数据"
                        ),
                        details={
                            "release_type": release_type,
                        },
                    )
                ],
                as_of=snapshot.as_of,
            ))
    return results