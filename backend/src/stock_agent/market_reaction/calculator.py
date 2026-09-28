from datetime import datetime, timedelta
from decimal import Decimal

from stock_agent.market.schemas import Bar
from stock_agent.market_reaction.alignment import EventMarketAlignment
from stock_agent.market_reaction.models import (
    MarketReactionResult,
    ObservationResult,
    select_observation_bar,
    select_reference_bar,
)


WINDOWS = {
    "5m": timedelta(minutes=5),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
}


def calculate_market_reaction(
    prepared: EventMarketAlignment,
) -> MarketReactionResult:
    """计算宏观事件后 5m、30m、1h 的实际收益率。"""
    event_at = prepared.event_at
    as_of = prepared.as_of

    if not event_at:
        return MarketReactionResult(
            release_id=prepared.release_id,
            release_type=prepared.release_type,
            symbol=prepared.symbol,
            event_at=None,
            reference_price=None,
            reference_at=None,
            observations={},
            issues=list(prepared.issues),
        )

    reference_bar = select_reference_bar(
        event_at=event_at,
        pre_bars=prepared.pre_bars,
    )

    if reference_bar is None:
        return MarketReactionResult(
            release_id=prepared.release_id,
            release_type=prepared.release_type,
            symbol=prepared.symbol,
            event_at=event_at,
            reference_price=None,
            reference_at=None,
            observations={
                name: ObservationResult(
                    target_at=event_at + offset,
                    status="unavailable",
                    reason="reference_bar_unavailable",
                )
                for name, offset in WINDOWS.items()
            },
            issues=list(prepared.issues),
        )

    reference_price = Decimal(str(reference_bar.close))
    observations: dict[str, ObservationResult] = {}

    for name, offset in WINDOWS.items():
        target_at = event_at + offset

        if target_at > as_of:
            observations[name] = ObservationResult(
                target_at=target_at,
                status="pending",
                reason="observation_not_yet_reached",
            )
            continue

        observation_bar = select_observation_bar(
            target_at=target_at,
            post_bars=prepared.post_bars,
            as_of=as_of,
        )

        if observation_bar is None:
            observations[name] = ObservationResult(
                target_at=target_at,
                status="missing",
                reason="observation_bar_unavailable",
            )
            continue

        price = Decimal(str(observation_bar.close))
        pct = (price / reference_price - Decimal("1")) * Decimal("100")

        observations[name] = ObservationResult(
            target_at=target_at,
            status="usable",
            price=price,
            price_at=observation_bar.end_at,
            return_pct=pct,
        )

    return MarketReactionResult(
        release_id=prepared.release_id,
        release_type=prepared.release_type,
        symbol=prepared.symbol,
        event_at=event_at,
        reference_price=reference_price,
        reference_at=reference_bar.end_at,
        observations=observations,
        issues=list(prepared.issues),
    )


def calculate_close_observation(
    *,
    close_at: datetime,
    as_of: datetime,
    reference_price: Decimal | None,
    reference_adjustment: str | None,
    daily_bar: Bar | None,
) -> ObservationResult:
    """计算正式收盘观察点的收益率。

    daily_bar 必须已经确认属于目标交易日，
    使用同一种价格调整口径。
    """

    if reference_price is None:
        return ObservationResult(
            target_at=close_at,
            status="unavailable",
            reason="reference_bar_unavailable",
        )
    if close_at > as_of:
        return ObservationResult(
            target_at=close_at,
            status="pending",
            reason="close_not_yet_reached",
        )
    if daily_bar is None:
        return ObservationResult(
            target_at=close_at,
            status="missing",
            reason="daily_close_unavailable",
        )
    if not daily_bar.is_complete:
        return ObservationResult(
            target_at=close_at,
            status="pending",
            reason="daily_bar_not_complete",
        )
    if daily_bar.updated_at is None:
        return ObservationResult(
            target_at=close_at,
            status="missing",
            reason="daily_close_time_unverified",
        )

    if daily_bar.updated_at > as_of:
        return ObservationResult(
            target_at=close_at,
            status="pending",
            reason="daily_close_not_yet_available",
        )

    if daily_bar.adjustment != reference_adjustment:
        return ObservationResult(
            target_at=close_at,
            status="unavailable",
            reason="price_adjustment_mismatch",
        )
    close_price = Decimal(str(daily_bar.close))

    return ObservationResult(
        target_at=close_at,
        status="usable",
        price=close_price,
        price_at=close_at,
        return_pct=(close_price / reference_price - Decimal("1"))
        * Decimal("100"),
    )
