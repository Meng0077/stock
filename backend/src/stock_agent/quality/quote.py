from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, validate_call

from stock_agent.market.schemas import Quote
from stock_agent.quality.models import (
    DataQualityResult,
    QualityIssue,
    QualityStatus,
)


MarketState = Literal[
    "trading",
    "closed",
    "unknown",
]

# 暂定阈值，后续结合实际行情源调整。
MAX_QUOTE_AGE_SECONDS = 60

@validate_call
def validate_quote(
    *,
    quote: Quote | None,
    symbol: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
    as_of: AwareDatetime,
    market_state: MarketState,
    max_age_seconds: Annotated[int, Field(gt=0, strict=True)] = MAX_QUOTE_AGE_SECONDS,
) -> DataQualityResult:
    # 检查一条报价是否适合当前价格分析

    target_id = symbol.upper()

    def make_result(
        status: QualityStatus,
        issues: list[QualityIssue],
    ) -> DataQualityResult:
        return DataQualityResult(
            data_kind="quote",
            target_id=target_id,
            purpose="current_price",
            status=status,
            issues=issues,
            as_of=as_of,
        )

    # 缺失报价或股票代码不匹配
    if not quote:
        return make_result("rejected", issues=[QualityIssue(
            code="quote_missing",
            message="未获取到股票报价",
        )])

    if  quote.symbol.strip().upper() != target_id:
        return make_result("rejected", issues=[QualityIssue(
            code="symbol_mismatch",
            message="报价所属股票与请求不一致",
        )])

    # 检查时间有效性
    if quote.quoted_at > as_of:
        return make_result("rejected", issues=[QualityIssue(
                    code="quote_after_as_of",
                    message="报价发生时间晚于研究截止时间",
                )])
    if quote.quoted_at > quote.received_at:
        return make_result(
            "rejected",
            [
                QualityIssue(
                    code="quote_after_received_at",
                    message="报价发生时间晚于系统接收时间",
                )
            ],
        )



    # 教学数据不能冒充真实当前价格
    if quote.data_mode == 'fixture':
        return make_result("rejected", issues=[QualityIssue(
                    code="fixture_not_current_price",
                    message="教学模拟报价不能用于真实价格分析",
                )])

    passed_time = (as_of - quote.quoted_at).total_seconds()

    # 检查市场状态及新鲜度
    if market_state == 'closed':
        return make_result("degraded", issues=[
            QualityIssue(
                code="market_closed",
                message=(
                    "市场已休市，可以展示报价及其时间，"
                    "但不能将其视为实时价格或"
                    "未经核实的最近收盘价"
                ),
                details={
                    "quote_age_seconds": passed_time,
                },
            )])

    # trading 和 unknown 都必须校验新鲜度。
    # unknown 只降低可信度，不能让过期报价绕过检查。
    if passed_time > max_age_seconds:
        return make_result('rejected', issues=[QualityIssue(
            code="quote_stale",
                    message="报价超过允许的新鲜度阈值",
                    details={
                        "quote_age_seconds": passed_time,
                        "max_age_seconds": max_age_seconds,
                    },
        )])

    if market_state == "unknown":
        return make_result("degraded", issues=[QualityIssue(
                    code="market_state_unknown",
                    message="无法确认当前市场交易状态",
                )])

    # 收集不会直接否定报价的质量问题
    issues: list[QualityIssue] = []
    if quote.data_mode != "live":
        issues.append(
            QualityIssue(
                code="quote_not_live",
                message="报价不是实时数据模式",
            )
        )

    if quote.is_delayed is True:
        issues.append(
            QualityIssue(
                code="quote_delayed",
                message="供应商标记该报价为延迟行情",
            )
        )
    elif quote.is_delayed is None:
        issues.append(
            QualityIssue(
                code="quote_delay_unknown",
                message="供应商未明确报价是否延迟",
            )
        )
    if issues:
        return make_result("degraded", issues)

    return make_result("usable", [])
