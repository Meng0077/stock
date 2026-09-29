from collections.abc import Sequence
from datetime import datetime

from stock_agent.macro.models.release import (
    MacroReleaseEvent,
    MacroReleaseType,
)
from stock_agent.market_reaction.event_time import resolve_event_time


def select_historical_releases(
    releases: Sequence[MacroReleaseEvent],
    *,
    release_type: MacroReleaseType,
    before: datetime,
    as_of: datetime,
    limit: int = 5,
) -> list[MacroReleaseEvent]:
    """筛选最近 N 次具有有效实际发布时间的同类事件。"""

    if before.tzinfo is None or before.utcoffset() is None:
        raise ValueError("before must be timezone-aware")

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    if limit <= 0:
        raise ValueError("limit must be positive")

    # 同时满足用户指定的历史边界和数据可见时间。
    cutoff = min(before, as_of)

    eligible: list[tuple[datetime, MacroReleaseEvent]] = []
    for release in releases:
        if release.release_type != release_type:
            continue

        resolution = resolve_event_time(
            release,
            as_of=cutoff,
        )
        if resolution.event_at is None:
            continue
        # before 是严格的时间边界。
        if resolution.event_at >= cutoff:
            continue

        eligible.append((resolution.event_at, release))

    eligible.sort(
        key=lambda item: (
            item[0],
            item[1].release_id,
        ),
        reverse=True,
    )

    return [release for _, release in eligible[:limit]]
