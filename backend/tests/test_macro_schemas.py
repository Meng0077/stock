from datetime import date, datetime, timezone
from decimal import Decimal
import typing

from stock_agent.macro.models.fed import (
    FedDotProjection,
    FedDotProjectionRelease,
    FedPolicyEvent,
)
from stock_agent.macro.models.metric import EconomicObservation
from stock_agent.macro.models.treasury import (
    TreasuryTenor,
    TreasuryYield,
)


def test_monthly_economic_observation():
    """验证月度经济指标的数据契约。"""

    observation = EconomicObservation(
        indicator="cpi",
        measure="yoy",
        unit="percent",
        frequency="monthly",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        seasonal_adjustment="nsa",
        value=Decimal("2.8"),
        released_at=datetime(
            2026, 9, 10, 12, 30,
            tzinfo=timezone.utc,
        ),
        source="fixture",
    )

    assert observation.indicator == "cpi"
    assert observation.measure == "yoy"
    assert observation.value == Decimal("2.8")
    assert observation.period_end == date(2026, 8, 31)
    
    print('success')


def test_fed_models():
    """验证利率决议和点阵图可以独立建模。"""

    released_at = datetime(
        2026, 6, 17, 18, 0,
        tzinfo=timezone.utc,
    )

    decision = FedPolicyEvent(
        meeting_date=date(2026, 6, 17),
        target_lower=Decimal("3.75"),
        target_upper=Decimal("4.00"),
        released_at=released_at,
        source="fixture",
    )

    sep = FedDotProjectionRelease(
        meeting_date=date(2026, 6, 17),
        released_at=released_at,
        projections=[
            FedDotProjection(
                target_year=2027,
                dots=[
                    Decimal("3.25"),
                    Decimal("3.50"),
                    Decimal("3.50"),
                    Decimal("3.75"),
                    Decimal("4.00"),
                ],
                published_median=Decimal("3.50"),
            ),
            FedDotProjection(
                target_year="longer_run",
                dots=[
                    Decimal("2.75"),
                    Decimal("3.00"),
                    Decimal("3.25"),
                ],
                published_median=Decimal("3.00"),
            ),
        ],
        source="fixture",
    )

    assert decision.target_lower == Decimal("3.75")

    # 重复的点不能被去掉。
    assert sep.projections[0].dots.count(
        Decimal("3.50")
    ) == 2

    assert sep.projections[1].target_year == "longer_run"
    
    print('success')


def test_treasury_yield_contract():
    """验证日频国债收益率的基本数据契约。"""

    yields = [
        TreasuryYield(
            observation_date=date(2026, 9, 22),
            tenor=typing.cast(TreasuryTenor, tenor),
            yield_pct=Decimal(value),
            source="fixture",
        )
        for tenor , value in [
            ("3m", "3.60"),
            ("2y", "3.80"),
            ("10y", "4.20"),
            ("30y", "4.70"),
        ]
    ]

    assert len(yields) == 4
    assert yields[2].tenor == "10y"
    assert yields[2].yield_pct == Decimal("4.20")

    # 不知道精确发布时间时，不伪造时间。
    assert yields[2].released_at is None

    assert all(
        item.curve_type == "nominal_cmt_h15"
        for item in yields
    )

def main():
    # test_monthly_economic_observation()
    test_fed_models()

if __name__ == '__main__':
    main()
