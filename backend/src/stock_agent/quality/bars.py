from typing import Annotated

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    validate_call,
)

from stock_agent.market.schemas import (
    Bar,
    BarTimeframe,
)
from stock_agent.quality.models import (
    DataQualityResult,
    QualityIssue,
    QualityStatus,
)



@validate_call
def validate_bars(
    *,
    bars: list[Bar],
    symbol: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
    timeframe: BarTimeframe,
    as_of: AwareDatetime,
    required_completed_bars: Annotated[int, Field(gt=0, strict=True)] = 60,
    allow_incomplete: bool = False,
) -> DataQualityResult:

    target_id = symbol.upper()


    def make_result(
        status: QualityStatus,
        issues: list[QualityIssue],
    ) -> DataQualityResult:
        return DataQualityResult(
            data_kind="bars",
            target_id=target_id,
            purpose="daily_technical",
            status=status,
            issues=issues,
            as_of=as_of,
        )

    if not bars:
        return make_result("rejected", issues=[QualityIssue(
            code="bars_missing",
            message="未获取到 K 线数据",
        )])

    for bar in bars:
        if bar.symbol.strip().upper() != target_id:
            return make_result("rejected", issues=[QualityIssue(
                    code="bar_symbol_mismatch",
                    message="K 线所属股票与请求股票不一致",
                    details={
                        "expected_symbol": target_id,
                        "actual_symbol": bar.symbol,
                    },
                )])

        if bar.timeframe != timeframe:
            return make_result("rejected", issues=[QualityIssue(
                    code="bar_timeframe_mismatch",
                    message="K 线周期不一致",
                    details={
                        "expected_timeframe": timeframe,
                        "actual_timeframe": bar.timeframe,
                    },
                )])
    adjustments = {bar.adjustment for bar in bars}
    if len(adjustments) != 1:
        return make_result("rejected", issues=[QualityIssue(
                code="mixed_bar_adjustment",
                message="K 线使用了不同的复权口径",
                details={
                    "adjustments": sorted(adjustments),
                },
            )])

    # 时间顺序
    for i in range(len(bars) - 1):
        cur, nxt = bars[i], bars[i+1]
        if nxt.start_at < cur.start_at:
            return make_result("rejected", issues=[QualityIssue(
                    code="bars_not_sorted",
                    message="K 线未按时间从旧到新排列",
                )])

    # 重复 Bar
    seen_intervals: set[tuple[object, object]] = set()
    for bar in bars:
        temp = (bar.start_at, bar.end_at)
        if temp in seen_intervals:
            return make_result("rejected", issues=[QualityIssue(
                    code="duplicate_bar",
                    message="发现重复 K 线时间区间",
                    details={
                        "start_at": bar.start_at.isoformat(),
                        "end_at": bar.end_at.isoformat()
                    }
                )])
        seen_intervals.add(temp)

    # 未来数据
    for bar in bars:
        if bar.start_at > as_of:
            return make_result("rejected", issues=[QualityIssue(
                        code="bar_from_future",
                        message="K 线开始时间晚于研究截止时间",
                    )])

        if bar.is_complete and bar.end_at > as_of:
            return make_result("rejected", issues=[QualityIssue(
                        code="completed_bar_from_future",
                        message=(
                            "标记为完成的 K 线结束时间"
                            "晚于研究截止时间"
                        ),
                    )])

    incomplete_bars = [bar for bar in bars if not bar.is_complete]
    if len(incomplete_bars) > 1:
        return make_result("rejected", issues=[QualityIssue(
                code="multiple_incomplete_bars",
                message="同时存在多根未完成 K 线",
            )])

    if incomplete_bars and bars[-1].is_complete:
        return make_result("rejected", issues=[QualityIssue(
                    code="incomplete_bar_not_last",
                    message="未完成 K 线不是序列最后一根",
                )])

    if not allow_incomplete and incomplete_bars:
        return make_result("rejected", issues=[QualityIssue(
                    code="incomplete_bar_not_allowed",
                    message="当前分析不允许使用未完成 K 线",
                )])

    # 历史窗口
    completed_bars = [bar for bar in bars if bar.is_complete]
    if not completed_bars:
        return make_result(
            "rejected",
            [
                QualityIssue(
                    code="completed_bars_missing",
                    message="没有可用于历史技术分析的完成 K 线",
                )
            ],
        )

    issues: list[QualityIssue] = []

    if len(completed_bars) < required_completed_bars:
        issues.append(QualityIssue(
            code="bar_window_insufficient",
                message="完成 K 线数量不足默认技术分析窗口",
                details={
                    "completed_bars": len(
                        completed_bars
                    ),
                    "required_completed_bars": (
                        required_completed_bars
                    ),
                },
        ))

    requirements = {
        "ma5": 5,
        "return_5d": 6,
        "atr14": 15,
        "ma20": 20,
        "price_structure_20d": 20,
        "return_20d": 21,
        "volume_20d": 21,
        "ma50": 50,
    }

    completed_count = len(completed_bars)

    unavailable = {
        indicator: required
        for indicator, required
        in requirements.items()
        if completed_count < required
    }

    if unavailable:
        issues.append(
            QualityIssue(
                code="technical_windows_unavailable",
                message="部分技术指标历史窗口不足",
                details={
                    "completed_bars": completed_count,
                    "requirements": unavailable,
                },
            )
        )

    if issues:
        return make_result("degraded", issues=issues)
    return make_result("usable", [])
