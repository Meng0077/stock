from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from stock_agent.macro.models.metric import MacroMetricSnapshot
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.temporal import (
    filter_releases_as_of,
    validate_metric_as_of,
    validate_release_as_of,
)


EASTERN = ZoneInfo("America/New_York")


def make_metric(
    *,
    release_date: date = date(2026, 9, 11),
    released_at: datetime | None = None,
    pit_status: str = "unverified",
) -> MacroMetricSnapshot:
    return MacroMetricSnapshot(
        indicator="cpi",
        measure="mom",
        unit="percent",
        period=date(2026, 8, 1),
        actual=Decimal("0.4"),
        release_date=release_date,
        released_at=released_at,
        source="fixture",
        actual_pit_status=pit_status,
    )


def make_release(
    *,
    release_date: date = date(2026, 9, 11),
    released_at: datetime | None = None,
    period_binding: str = "latest_assumed",
    metrics: list[MacroMetricSnapshot] | None = None,
) -> MacroReleaseEvent:
    return MacroReleaseEvent(
        release_id=f"cpi:{release_date.isoformat()}",
        release_type="cpi",
        release_date=release_date,
        released_at=released_at,
        release_date_source="fixture",
        period_binding=period_binding,
        metrics=metrics or [
            make_metric(
                release_date=release_date,
                released_at=released_at,
            )
        ],
    )


def test_date_only_release_is_rejected_until_next_eastern_day():
    release = make_release()

    same_eastern_day = validate_release_as_of(
        release,
        as_of=datetime(2026, 9, 12, 1, tzinfo=timezone.utc),
    )
    next_eastern_day = validate_release_as_of(
        release,
        as_of=datetime(2026, 9, 12, 5, tzinfo=timezone.utc),
    )

    assert same_eastern_day.decision == "reject"
    assert same_eastern_day.reason == "exact_release_time_unverified"
    assert next_eastern_day.decision == "usable_with_warning"
    assert next_eastern_day.reason == "release_period_binding_unverified"


def test_precise_release_time_blocks_future_and_accepts_past():
    released_at = datetime(2026, 9, 11, 8, 30, tzinfo=EASTERN)
    release = make_release(
        released_at=released_at,
        period_binding="verified",
    )

    before = validate_release_as_of(
        release,
        as_of=datetime(2026, 9, 11, 8, 29, tzinfo=EASTERN),
    )
    after = validate_release_as_of(
        release,
        as_of=datetime(2026, 9, 11, 8, 30, tzinfo=EASTERN),
    )

    assert before.reason == "release_not_yet_published"
    assert before.decision == "reject"
    assert after.reason == "release_available"
    assert after.decision == "usable"


def test_release_date_and_precise_time_must_agree():
    release = make_release(
        released_at=datetime(2026, 9, 12, 8, 30, tzinfo=EASTERN),
    )

    validation = validate_release_as_of(
        release,
        as_of=datetime(2026, 9, 12, 9, tzinfo=EASTERN),
    )

    assert validation.decision == "reject"
    assert validation.reason == "release_date_time_conflict"


def test_strict_pit_rejects_date_only_or_unbound_release():
    date_only = validate_release_as_of(
        make_release(),
        as_of=datetime(2026, 9, 13, tzinfo=timezone.utc),
        strict_pit=True,
    )
    unbound = validate_release_as_of(
        make_release(
            released_at=datetime(2026, 9, 11, 8, 30, tzinfo=EASTERN),
        ),
        as_of=datetime(2026, 9, 13, tzinfo=timezone.utc),
        strict_pit=True,
    )

    assert date_only.reason == "exact_release_time_missing"
    assert unbound.reason == "release_period_binding_unverified"


def test_filter_releases_removes_metrics_that_fail_strict_pit():
    release = make_release(
        released_at=datetime(2026, 9, 11, 8, 30, tzinfo=EASTERN),
        period_binding="verified",
        metrics=[
            make_metric(
                released_at=datetime(
                    2026, 9, 11, 8, 30, tzinfo=EASTERN
                ),
                pit_status="unverified",
            )
        ],
    )

    releases, warnings = filter_releases_as_of(
        [release],
        as_of=datetime(2026, 9, 13, tzinfo=timezone.utc),
        strict_pit=True,
    )

    assert releases == []
    assert warnings == [
        "cpi:2026-09-11:cpi:mom:actual_pit_unverified",
        "cpi:2026-09-11:no_usable_metrics",
    ]


def test_release_validation_requires_timezone_aware_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_release_as_of(
            make_release(),
            as_of=datetime(2026, 9, 12),
        )


def test_metric_validation_uses_eastern_date_and_rejects_naive_release_time():
    future_date = validate_metric_as_of(
        make_metric(release_date=date(2026, 9, 12)),
        as_of=datetime(2026, 9, 12, 1, tzinfo=timezone.utc),
        strict_pit=False,
    )
    naive_time = validate_metric_as_of(
        make_metric(released_at=datetime(2026, 9, 11, 8, 30)),
        as_of=datetime(2026, 9, 12, tzinfo=timezone.utc),
        strict_pit=False,
    )

    assert future_date.decision == "reject"
    assert future_date.reason == "release_date_after_as_of"
    assert naive_time.decision == "reject"
    assert naive_time.reason == "invalid_release_timestamp"


def test_metric_validation_requires_timezone_aware_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_metric_as_of(
            make_metric(),
            as_of=datetime(2026, 9, 12),
            strict_pit=False,
        )
