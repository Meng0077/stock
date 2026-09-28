from dataclasses import dataclass
from datetime import datetime, timezone

from stock_agent.macro.models.release import (
    MacroReleaseEvent,
)
from stock_agent.macro.temporal import (
    validate_release_as_of,
)


@dataclass(frozen=True, slots=True)
class EventTimeResolution:
    """宏观事件实际发布时间的解析结果。"""

    # 统一转换成 UTC，无法解析时为 None。
    event_at: datetime | None

    # 无法使用分钟级事件时间的原因。
    reason: str | None = None

    # 可以使用，但仍存在的时间证据问题。
    warning: str | None = None


def resolve_event_time(
    release: MacroReleaseEvent,
    *,
    as_of: datetime,
) -> EventTimeResolution:
    """解析可用于分钟级市场反应的实际发布时间。

    不将 scheduled_release_at 推断为 released_at。
    """
    if (
        as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise ValueError(
            "as_of must be timezone-aware"
        )

    if release.released_at is None:
        return EventTimeResolution(
            event_at=None,
            reason="actual_release_time_missing",
        )

    validation = validate_release_as_of(release, as_of=as_of, strict_pit=False)
    if validation.decision == "reject":
        return EventTimeResolution(
            event_at=None,
            reason=validation.reason,
        )

    return EventTimeResolution(
        event_at=release.released_at.astimezone(timezone.utc),
        warning=(
            validation.reason
            if validation.decision == "usable_with_warning"
            else None
        ),
    )
