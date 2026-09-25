from decimal import Decimal

from stock_agent.macro.models.fed import FedPolicySnapshot, FedTargetRange


def build_policy_snapshot(
    ranges: list[FedTargetRange],
) -> FedPolicySnapshot | None:
    if not ranges:
        return None

    current = ranges[-1]
    previous = ranges[-2] if len(ranges) >= 2 else None

    return FedPolicySnapshot(
        current=current,
        previous=previous,
        lower_change_bps=(
            (current.target_lower - previous.target_lower) * Decimal("100")
            if previous is not None
            else None
        ),
        upper_change_bps=(
            (current.target_upper - previous.target_upper) * Decimal("100")
            if previous is not None
            else None
        ),
    )
