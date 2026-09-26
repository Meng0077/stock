from datetime import date
from decimal import Decimal

import pytest

from stock_agent.macro.calculations.fed import build_policy_snapshot
from stock_agent.macro.calculations.treasury import build_treasury_snapshot
from stock_agent.macro.models.fed import FedTargetRange
from stock_agent.macro.models.treasury import TreasuryYield


def test_policy_snapshot_calculates_basis_point_change():
    snapshot = build_policy_snapshot(
        [
            FedTargetRange(
                effective_date=date(2026, 6, 18),
                target_lower=Decimal("4.25"),
                target_upper=Decimal("4.50"),
            ),
            FedTargetRange(
                effective_date=date(2026, 9, 17),
                target_lower=Decimal("4.00"),
                target_upper=Decimal("4.25"),
            ),
        ]
    )

    assert snapshot is not None
    assert snapshot.current.effective_date == date(2026, 9, 17)
    assert snapshot.lower_change_bps == Decimal("-25.00")
    assert snapshot.upper_change_bps == Decimal("-25.00")


def make_curve(observation_date: date, values: tuple[str, str, str, str]):
    return [
        TreasuryYield(
            observation_date=observation_date,
            tenor=tenor,
            yield_pct=Decimal(value),
        )
        for tenor, value in zip(("3m", "2y", "10y", "30y"), values)
    ]


def test_treasury_snapshot_uses_latest_complete_curve_and_previous_curve():
    observations = [
        *make_curve(
            date(2026, 9, 23),
            ("4.10", "3.80", "4.00", "4.30"),
        ),
        *make_curve(
            date(2026, 9, 24),
            ("4.08", "3.82", "4.05", "4.35"),
        ),
        TreasuryYield(
            observation_date=date(2026, 9, 25),
            tenor="10y",
            yield_pct=Decimal("4.07"),
        ),
        *make_curve(
            date(2026, 9, 27),
            ("4.00", "3.70", "3.90", "4.20"),
        ),
    ]

    snapshot = build_treasury_snapshot(
        observations=observations,
        as_of=date(2026, 9, 26),
    )

    assert snapshot is not None
    assert snapshot.observation_date == date(2026, 9, 24)
    assert snapshot.previous_observation_date == date(2026, 9, 23)
    assert snapshot.daily_change_bps == {
        "3m": Decimal("-2.00"),
        "2y": Decimal("2.00"),
        "10y": Decimal("5.00"),
        "30y": Decimal("5.00"),
    }
    assert snapshot.spread_10y_2y_bps == Decimal("23.00")
    assert snapshot.spread_10y_3m_bps == Decimal("-3.00")
    assert snapshot.age_days == 2
    assert snapshot.is_stale is False


def test_treasury_snapshot_requires_same_day_complete_curve():
    observations = make_curve(
        date(2026, 9, 20),
        ("4.10", "3.80", "4.00", "4.30"),
    )[:-1]

    assert build_treasury_snapshot(
        observations=observations,
        as_of=date(2026, 9, 26),
    ) is None


def test_treasury_snapshot_rejects_conflicting_duplicate():
    observations = make_curve(
        date(2026, 9, 24),
        ("4.08", "3.82", "4.05", "4.35"),
    )
    observations.append(
        TreasuryYield(
            observation_date=date(2026, 9, 24),
            tenor="10y",
            yield_pct=Decimal("4.06"),
        )
    )

    with pytest.raises(ValueError, match="Duplicate Treasury observation"):
        build_treasury_snapshot(
            observations=observations,
            as_of=date(2026, 9, 26),
        )
