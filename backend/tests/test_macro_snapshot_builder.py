from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

import stock_agent.macro.builder as builder_module
from stock_agent.macro.builder import MacroSnapshotBuilder
from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.models.metric import MacroMetricSnapshot
from stock_agent.macro.models.release import MacroReleaseEvent


AS_OF = datetime(2026, 9, 20, 16, tzinfo=timezone.utc)


def make_release(release_type: str, release_date: date) -> MacroReleaseEvent:
    released_at = datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        12,
        30,
        tzinfo=timezone.utc,
    )
    return MacroReleaseEvent(
        release_id=f"{release_type}:{release_date.isoformat()}",
        release_type=release_type,
        release_date=release_date,
        released_at=released_at,
        release_date_source="fixture",
        period_binding="verified",
        metrics=[
            MacroMetricSnapshot(
                indicator=(
                    "initial_claims"
                    if release_type == "weekly_claims"
                    else "nonfarm_payrolls"
                    if release_type == "employment_situation"
                    else "cpi"
                ),
                measure=(
                    "level"
                    if release_type == "weekly_claims"
                    else "monthly_change"
                    if release_type == "employment_situation"
                    else "mom"
                ),
                unit=(
                    "persons"
                    if release_type == "weekly_claims"
                    else "jobs"
                    if release_type == "employment_situation"
                    else "percent"
                ),
                period=date(2026, 8, 1),
                actual=Decimal("1"),
                release_date=release_date,
                released_at=released_at,
                source="fixture",
                actual_pit_status="verified",
            )
        ],
    )


class FakeFed:
    def get_target_ranges(self, *, as_of: date):
        assert as_of == date(2026, 9, 20)
        return []

    def get_current_projections(self, *, as_of: date):
        raise MacroDataProviderError("fed projections unavailable")


class FakeTreasury:
    def get_yields(self, tenors: list[str], *, as_of: date):
        assert as_of == date(2026, 9, 20)
        return []


def make_builder() -> MacroSnapshotBuilder:
    unused = object()
    return MacroSnapshotBuilder(
        bls=unused,  # type: ignore[arg-type]
        bea=unused,  # type: ignore[arg-type]
        consensus=None,
        fred=unused,  # type: ignore[arg-type]
        fed=FakeFed(),  # type: ignore[arg-type]
        treasury=FakeTreasury(),  # type: ignore[arg-type]
        claims=unused,  # type: ignore[arg-type]
    )


def test_snapshot_builder_returns_partial_result_and_specific_warnings(monkeypatch):
    def build_inflation(*, release_type: str, **kwargs):
        if release_type == "ppi":
            raise MacroDataProviderError("ppi unavailable")
        return make_release("cpi", date(2026, 9, 18))

    monkeypatch.setattr(
        builder_module,
        "build_bls_inflation_release",
        build_inflation,
    )
    monkeypatch.setattr(
        builder_module,
        "build_pce_release",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_module,
        "build_employment_release",
        lambda **kwargs: make_release(
            "employment_situation", date(2026, 9, 17)
        ),
    )
    monkeypatch.setattr(
        builder_module,
        "build_weekly_claims_release",
        lambda **kwargs: make_release(
            "weekly_claims", date(2026, 9, 19)
        ),
    )

    snapshot = make_builder().build_latest(as_of=AS_OF)

    assert [release.release_type for release in snapshot.recent_releases] == [
        "weekly_claims",
        "cpi",
        "employment_situation",
    ]
    assert snapshot.fed_policy is None
    assert snapshot.fed_projections == []
    assert snapshot.treasury is None
    assert set(snapshot.warnings) == {
        "ppi_release_unavailable",
        "pce_release_missing",
        "fed_policy_missing",
        "fed_projections_unavailable",
        "treasury_data_missing",
    }


def test_snapshot_builder_does_not_hide_programming_errors(monkeypatch):
    monkeypatch.setattr(
        builder_module,
        "build_bls_inflation_release",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bug")),
    )

    with pytest.raises(RuntimeError, match="bug"):
        make_builder().build_latest(as_of=AS_OF)


def test_snapshot_builder_requires_timezone_aware_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_builder().build_latest(as_of=datetime(2026, 9, 20, 16))
