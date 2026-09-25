from datetime import date
from decimal import Decimal
from typing import Protocol


class SeriesPoint(Protocol):
    period: date
    value: Decimal


def shift_month(period: date, months: int) -> date:
    """Return the first day of the month at the requested offset."""

    total = period.year * 12 + period.month - 1 + months
    year, month_index = divmod(total, 12)
    return date(year, month_index + 1, 1)


def calculate_index_change(
    index: dict[date, Decimal],
    *,
    current: date,
    previous: date,
) -> Decimal | None:
    """Calculate a percentage change between two index observations."""

    current_value = index.get(current)
    previous_value = index.get(previous)

    if current_value and previous_value:
        return (current_value / previous_value - 1) * Decimal("100")
    return None
