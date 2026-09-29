from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from stock_agent.market_reaction.models import (
    MarketReactionResult,
    ObservationResult,
    ObservationStatus,
)
from stock_agent.market_reaction.multi_symbol import (
    MultiSymbolEventReaction,
)


WINDOWS = ("5m", "30m", "1h", "close")

STATUS_PRIORITY = {
    "usable": 0,
    "pending": 1,
    "missing": 2,
    "unavailable": 3,
}


@dataclass(frozen=True)
class RelativeObservation:
    lhs_return_pct: Decimal | None
    rhs_return_pct: Decimal | None

    # 两个百分比收益率之差，单位是百分点。
    difference_pp: Decimal | None

    lhs_status: ObservationStatus
    rhs_status: ObservationStatus
    status: ObservationStatus

    lhs_reason: str | None = None
    rhs_reason: str | None = None


@dataclass(frozen=True)
class ReactionComparison:
    release_id: str
    release_type: str
    event_at: datetime | None

    lhs_symbol: str
    rhs_symbol: str

    observations: dict[str, RelativeObservation]
    issues: list[str]


def compare_observations(
    lhs: ObservationResult | None,
    rhs: ObservationResult | None,
) -> RelativeObservation:
    """计算两个证券在同一观察窗口的收益率差。"""

    if lhs is not None and rhs is not None and lhs.target_at != rhs.target_at:
        raise ValueError("observation target times do not match")

    lhs_status = lhs.status if lhs is not None else "unavailable"
    rhs_status = rhs.status if rhs is not None else "unavailable"

    lhs_pct = lhs.return_pct if lhs is not None and lhs_status == "usable" else None
    rhs_pct = rhs.return_pct if rhs is not None and rhs_status == "usable" else None

    # usable 却没有收益率，属于上游数据结构错误。
    if lhs_status == "usable" and lhs_pct is None:
        raise ValueError("lhs usable observation has no return")

    if rhs_status == "usable" and rhs_pct is None:
        raise ValueError("rhs usable observation has no return")
    return RelativeObservation(
        lhs_return_pct=lhs_pct,
        rhs_return_pct=rhs_pct,
        difference_pp=(
            lhs_pct - rhs_pct
            if lhs_pct is not None and rhs_pct is not None
            else None
        ),
        lhs_status=lhs_status,
        rhs_status=rhs_status,
        status=max((lhs_status, rhs_status), key=lambda value: STATUS_PRIORITY[value]),
        lhs_reason=lhs.reason if lhs is not None else "observation_not_returned",
        rhs_reason=rhs.reason if rhs is not None else "observation_not_returned",
    )


def compare_market_reactions(
    *,
    lhs: MarketReactionResult,
    rhs: MarketReactionResult,
) -> ReactionComparison:
    """比较同一次宏观事件下两只证券的市场反应。"""

    if lhs.release_id != rhs.release_id or lhs.release_type != rhs.release_type:
        raise ValueError("releases do not match")

    if lhs.event_at != rhs.event_at:
        raise ValueError("event times do not match")

    observations = {
        window: compare_observations(
            lhs.observations.get(window),
            rhs.observations.get(window),
        )
        for window in WINDOWS
    }
    issues = [
        *(f"{lhs.symbol}:{issue}" for issue in lhs.issues),
        *(f"{rhs.symbol}:{issue}" for issue in rhs.issues),
    ]

    if (
        lhs.reference_at is not None
        and rhs.reference_at is not None
        and lhs.reference_at != rhs.reference_at
    ):
        issues.append("reference_timestamp_mismatch")

    return ReactionComparison(
        release_id=lhs.release_id,
        release_type=lhs.release_type,
        event_at=lhs.event_at,
        lhs_symbol=lhs.symbol,
        rhs_symbol=rhs.symbol,
        observations=observations,
        issues=issues,
    )


def compare_event_symbols(
    *,
    event: MultiSymbolEventReaction,
    lhs_symbol: str,
    rhs_symbol: str,
) -> ReactionComparison:
    """从已经查询好的多股票结果中选择两只进行比较。"""

    lhs_symbol = lhs_symbol.strip().upper()
    rhs_symbol = rhs_symbol.strip().upper()

    if lhs_symbol == rhs_symbol:
        raise ValueError("symbols must be different")

    if lhs_symbol not in event.reactions:
        raise ValueError(f"symbol not found: {lhs_symbol}")

    if rhs_symbol not in event.reactions:
        raise ValueError(f"symbol not found: {rhs_symbol}")

    return compare_market_reactions(
        lhs=event.reactions[lhs_symbol],
        rhs=event.reactions[rhs_symbol],
    )
