from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from collections import Counter

from stock_agent.market.intraday import (
    HistoricalMinuteBarsRequest,
    IntradayBar,
)



RequiredSession = Literal[
    "pre",
    "regular",
    "post",
    "overnight",
]

CoverageStatus = Literal[
    "all_observed",
    "partially_observed",
    "none_observed",
]



class IntradayCoverage(BaseModel):
    """历史分钟行情的交易时段覆盖摘要。

    这里只表示有没有观测到对应时段的数据，
    不表示时段内的所有分钟都完整。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    status: CoverageStatus

    required_sessions: list[RequiredSession]

    observed_counts: dict[RequiredSession, int]

    unobserved_sessions: list[RequiredSession]

    unknown_session_bars: int = Field(ge=0)

    first_bar_at: datetime | None = None

    last_bar_end_at: datetime | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )


def inspect_intraday_coverage(
    *,
    request: HistoricalMinuteBarsRequest,
    bars: list[IntradayBar],
    required_sessions: set[RequiredSession],
) -> IntradayCoverage:
    """统计指定查询窗口内的交易时段覆盖情况。"""

    if not required_sessions:
        raise ValueError(
            "required_sessions must not be empty"
        )

    symbol = request.symbol.upper()

    # 只统计本次请求范围内、已完成的分钟 K 线。
    observed_bars = [
        bar
        for bar in bars
        if (
            bar.symbol.strip().upper() == symbol
            and bar.start_at >= request.start_at
            and bar.end_at <= request.end_at
            and bar.end_at <= request.as_of
            and bar.is_complete
        )
    ]

    counts = Counter(bar.session for bar in observed_bars)


    required = sorted(required_sessions)

    observed_counts = {
        session: counts[session]
        for session in required
    }

    unobserved = [
        session
        for session in required
        if observed_counts[session] == 0
    ]

    if len(unobserved) == len(required):
        status = "none_observed"
    elif unobserved:
        status = "partially_observed"
    else:
        status = "all_observed"

    warnings: list[str] = []

    if unobserved:
        warnings.append(
            "required_sessions_not_observed"
        )

    if counts["unknown"] > 0:
        warnings.append(
            "unknown_trade_session_present"
        )

    return IntradayCoverage(
        status=status,
        required_sessions=required,
        observed_counts=observed_counts,
        unobserved_sessions=unobserved,
        unknown_session_bars=counts["unknown"],
        first_bar_at=(
            min(bar.start_at for bar in bars)
            if bars else None
        ),
        last_bar_end_at=(
            max(bar.end_at for bar in bars)
            if bars else None
        ),
        warnings=warnings,
    )
