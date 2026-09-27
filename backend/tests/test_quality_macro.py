from datetime import date, datetime, timezone
from decimal import Decimal

from stock_agent.macro.models.metric import MacroMetricSnapshot
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.models.snapshot import MacroSnapshot
from stock_agent.quality.macro import (
    check_required_macro_releases,
    validate_macro_release,
)


AS_OF = datetime(2026, 9, 20, 16, tzinfo=timezone.utc)
RELEASED_AT = datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)


def make_metric(**updates) -> MacroMetricSnapshot:
    values = {
        "indicator": "cpi",
        "measure": "mom",
        "unit": "percent",
        "period": date(2026, 8, 1),
        "actual": Decimal("0.3"),
        "release_date": date(2026, 9, 11),
        "released_at": RELEASED_AT,
        "source": "fixture",
        "actual_pit_status": "verified",
    }
    values.update(updates)
    return MacroMetricSnapshot(**values)


def make_release(
    *,
    metrics: list[MacroMetricSnapshot],
    release_date_source: str = "fixture",
) -> MacroReleaseEvent:
    return MacroReleaseEvent(
        release_id="cpi:2026-09-11",
        release_type="cpi",
        release_date=date(2026, 9, 11),
        released_at=RELEASED_AT,
        release_date_source=release_date_source,
        period_binding="verified",
        metrics=metrics,
    )


def test_macro_quality_degrades_unverified_release_date_source():
    result = validate_macro_release(
        release=make_release(
            metrics=[make_metric()],
            release_date_source="unknown_vendor",
        ),
        as_of=AS_OF,
    )

    assert result.status == "degraded"
    assert [issue.code for issue in result.issues] == [
        "release_date_source_unverified"
    ]


def test_macro_quality_degrades_unverified_consensus():
    result = validate_macro_release(
        release=make_release(
            metrics=[
                make_metric(
                    consensus=Decimal("0.2"),
                    consensus_source="longbridge",
                    consensus_pit_verified=False,
                )
            ]
        ),
        as_of=AS_OF,
    )

    assert result.status == "degraded"
    assert [issue.code for issue in result.issues] == [
        "consensus_pit_unverified"
    ]


def test_macro_quality_rejects_release_when_all_metrics_are_future():
    result = validate_macro_release(
        release=make_release(
            metrics=[
                make_metric(
                    release_date=date(2026, 9, 21),
                    released_at=None,
                )
            ]
        ),
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert [issue.code for issue in result.issues] == [
        "release_date_after_as_of",
        "no_usable_macro_metrics",
    ]


def test_required_macro_release_reports_missing_type():
    snapshot = MacroSnapshot(
        as_of=AS_OF,
        recent_releases=[],
        fed_policy=None,
        fed_projections=[],
        treasury=None,
        warnings=[],
    )

    results = check_required_macro_releases(
        snapshot=snapshot,
        required_types={"cpi"},
    )

    assert len(results) == 1
    assert results[0].status == "rejected"
    assert results[0].target_id == "cpi:latest"
    assert results[0].issues[0].code == "macro_release_missing"
