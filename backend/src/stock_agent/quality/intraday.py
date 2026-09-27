
from datetime import timedelta

from pydantic import validate_call

from stock_agent.market.intraday import (
    HistoricalMinuteBarsRequest,
    IntradayBar,
)
from stock_agent.market.intraday_coverage import (
    RequiredSession,
    inspect_intraday_coverage,
)
from stock_agent.quality.models import (
    DataQualityResult,
    QualityIssue,
    QualityStatus,
)

ONE_MINUTE = timedelta(minutes=1)

@validate_call
def validate_intraday_bars(
    *,
    request: HistoricalMinuteBarsRequest,
    bars: list[IntradayBar],
    required_sessions: list[RequiredSession],
) -> DataQualityResult:
    """检查历史分钟行情能否用于指定市场反应窗口。"""

    if not required_sessions:
        raise ValueError("required_sessions must not be empty")

    symbol = request.symbol.upper()
    issues: list[QualityIssue] = []

    def make_result(
            status: QualityStatus,
            issues: list[QualityIssue],
        ) -> DataQualityResult:
            return DataQualityResult(
                data_kind="bars",
                target_id=symbol,
                purpose="market_reaction",
                status=status,
                issues=issues,
                as_of=request.as_of,
            )

    previous = None

    # ---------- 1. 检查单根 K 线 ----------
    for bar in bars:
        if bar.symbol.strip().upper() != symbol:
            return make_result(
                "rejected",
                [QualityIssue(
                    code="intraday_symbol_mismatch",
                    message="分钟 K 线所属股票不一致",
                )],
            )

        if bar.end_at - bar.start_at != ONE_MINUTE:
            return make_result(
                "rejected",
                [QualityIssue(
                    code="invalid_minute_interval",
                    message="分钟 K 线长度不是一分钟",
                )],
            )

        if (
            bar.start_at.second != 0
            or bar.start_at.microsecond != 0
        ):
            return make_result(
                "rejected",
                [QualityIssue(
                    code="minute_not_aligned",
                    message="分钟 K 线未对齐整分钟",
                )],
            )

        if not bar.is_complete:
            return make_result(
                "rejected",
                [QualityIssue(
                    code="incomplete_intraday_bar",
                    message="不允许使用未完成分钟 K 线",
                )],
            )

        if (
            bar.start_at < request.start_at
            or bar.end_at > request.end_at
        ):
            return make_result(
                "rejected",
                [QualityIssue(
                    code="intraday_outside_window",
                    message="K 线超出请求时间范围",
                )],
            )

        if bar.end_at > request.as_of:
            return make_result(
                "rejected",
                [QualityIssue(
                    code="intraday_bar_from_future",
                    message="K 线结束时间晚于 as_of",
                )],
            )

        if (
            bar.updated_at is not None
            and bar.updated_at > request.as_of
        ):
            return make_result(
                "rejected",
                [QualityIssue(
                    code="intraday_update_after_as_of",
                    message="K 线更新时间晚于 as_of",
                )],
            )

        # ---------- 2. 检查时间顺序 ----------
        if previous is not None:

            if bar.start_at == previous.start_at:
                return make_result(
                    "rejected",
                    [QualityIssue(
                        code="duplicate_intraday_bar",
                        message="存在重复分钟 K 线",
                    )],
                )

            if bar.start_at < previous.start_at:
                return make_result(
                    "rejected",
                    [QualityIssue(
                        code="intraday_not_sorted",
                        message="分钟 K 线未按时间升序排列",
                    )],
                )

            if bar.start_at < previous.end_at:
                return make_result(
                    "rejected",
                    [QualityIssue(
                        code="overlapping_intraday_bars",
                        message="分钟 K 线时间区间重叠",
                    )],
                )

        previous = bar

        # ---------- 3. 检查统一数据口径 ----------

    adjustments = {
        bar.adjustment
        for bar in bars
    }

    if len(adjustments) > 1:
        return make_result(
            "rejected",
            [QualityIssue(
                code="mixed_intraday_adjustment",
                message="分钟行情混用了不同复权口径",
                details={
                    "adjustments": sorted(adjustments),
                },
            )],
        )

    data_modes = {
        bar.data_mode
        for bar in bars
    }

    if len(data_modes) > 1:
        return make_result(
            "rejected",
            [QualityIssue(
                code="mixed_intraday_data_mode",
                message="分钟行情混用了不同数据模式",
                details={
                    "data_modes": sorted(data_modes),
                },
            )],
        )

    # ---------- 4. 检查交易时段覆盖 ----------

    coverage = inspect_intraday_coverage(
        request=request,
        bars=bars,
        required_sessions=required_sessions,
    )

    if coverage.unobserved_sessions:
        issues.append(
            QualityIssue(
                code="required_sessions_not_observed",
                message="部分或全部必需交易时段未观察到行情",
                details={
                    "unobserved_sessions": (
                        coverage.unobserved_sessions
                    ),
                    "observed_counts": (
                        coverage.observed_counts
                    ),
                },
            )
        )

    if coverage.unknown_session_bars:
        issues.append(
            QualityIssue(
                code="unknown_trade_session",
                message="部分 K 线的交易时段未知",
                details={
                    "bar_count": (
                        coverage.unknown_session_bars
                    ),
                },
            )
        )

    # ---------- 5. 检查其他数据不确定性 ----------

    missing_updated_at = sum(
        bar.updated_at is None
        for bar in bars
    )

    if missing_updated_at:
        issues.append(
            QualityIssue(
                code="intraday_update_time_unknown",
                message="部分 K 线缺少更新时间",
                details={
                    "bar_count": missing_updated_at,
                },
            )
        )

    # ---------- 6. 确定质量状态 ----------

    if coverage.status == "none_observed":
        return make_result(
            "rejected",
            issues,
        )

    if issues:
        return make_result(
            "degraded",
            issues,
        )

    return make_result(
        "usable",
        [],
    )
