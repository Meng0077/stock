from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from stock_agent.macro.models.release import (
    MacroReleaseEvent,
)
from stock_agent.macro.temporal import (
    validate_release_as_of,
)

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class EventTimeResolution:
    """一次市场事件时间的解析结果。"""

    # 最终允许 Market Reaction 使用的 UTC 时间。
    event_at: datetime | None

    # 本次实际选择的时间来源。
    event_time_source: str | None = None

    # 完全不能形成事件时间时的原因。
    reason: str | None = None

    # 时间可用，但存在的限制。
    warnings: tuple[str, ...] = ()


def resolve_event_time(
    release: MacroReleaseEvent,
    *,
    as_of: datetime,
) -> EventTimeResolution:
    """
    解析可用于分钟级 Market Reaction 的事件时间。

    优先级：

    1. released_at
       已确认的实际发布时间；

    2. vendor_release_at
       供应商报告的事件时间，
       普通研究可以使用，但必须带 warning；

    3. scheduled_release_at
       仅是计划时间，不能作为实际事件锚点。
    """

    if (
        as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise ValueError(
            "as_of must be timezone-aware"
        )

    # -------------------------------------------------
    # 1. 优先使用已经确认的 released_at
    # -------------------------------------------------

    if release.released_at is not None:
        validation = validate_release_as_of(
            release,
            as_of=as_of,
            strict_pit=False,
        )

        if validation.decision == "reject":
            return EventTimeResolution(
                event_at=None,
                event_time_source=(
                    release.released_at_source
                ),
                reason=validation.reason,
            )

        warnings: list[str] = []

        if (
            validation.decision
            == "usable_with_warning"
        ):
            warnings.append(
                validation.reason
            )

        return EventTimeResolution(
            event_at=(
                release.released_at
                .astimezone(timezone.utc)
            ),
            event_time_source=(
                release.released_at_source
            ),
            warnings=tuple(warnings),
        )

    # -------------------------------------------------
    # 2. 没有 verified released_at，
    #    尝试 vendor timestamp
    # -------------------------------------------------

    vendor_release_at = (
        release.vendor_release_at
    )

    if vendor_release_at is not None:
        # 以下三项统一由 validate_release_as_of() 检查：
        # Vendor timestamp 自己也必须是
        # timezone-aware。
        # 不能使用 as_of 之后的事件时间。
        # Vendor timestamp 必须和
        # release_date 指向同一天。
        # 继续复用已有 Release 时间 / PIT 校验，
        # 不重新实现 release_date_source、
        # period_binding 等规则。
        validation = validate_release_as_of(
            release,
            as_of=as_of,
            strict_pit=False,
        )

        if validation.decision == "reject":
            return EventTimeResolution(
                event_at=None,
                event_time_source=(
                    release
                    .vendor_release_at_source
                ),
                reason=validation.reason,
            )

        warnings = [
            "event_time_uses_vendor_timestamp",
        ]

        if (
            validation.decision
            == "usable_with_warning"
            and validation.reason not in warnings
        ):
            warnings.append(
                validation.reason
            )

        return EventTimeResolution(
            event_at=(
                vendor_release_at
                .astimezone(timezone.utc)
            ),
            event_time_source=(
                release
                .vendor_release_at_source
            ),
            warnings=tuple(warnings),
        )

    # -------------------------------------------------
    # 3. scheduled_release_at 不能自动提升
    #    为实际事件时间
    # -------------------------------------------------

    return EventTimeResolution(
        event_at=None,
        reason="actual_release_time_missing",
    )
