"""长桥宏观指标映射及数值标准化。

只负责：
1. 长桥指标代码与内部指标名称的映射。
2. 将供应商数值转换为项目统一单位。

不负责网络请求、发布时间、Consensus 匹配或 PIT 校验。
"""


from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from stock_agent.macro.models.metric import (
    EconomicIndicator,
    EconomicMeasure,
    EconomicUnit,
)


Frequency = Literal["monthly", "weekly"]

IndicatorKey = tuple[EconomicIndicator, EconomicMeasure]


@dataclass(frozen=True)
class LongbridgeIndicatorSpec:
    code: str
    indicator: EconomicIndicator
    measure: EconomicMeasure
    unit: EconomicUnit

    # 将长桥返回的数值转换成项目内部的单位。
    scale: Decimal = Decimal("1")

    # 用于区分月度统计期和周度统计期。
    frequency: Frequency = "monthly"

LONGBRIDGE_INDICATORS: dict[
    IndicatorKey,
    LongbridgeIndicatorSpec,
] = {
    # ---------- CPI ----------
    ("cpi", "mom"): LongbridgeIndicatorSpec(
        "30771886", "cpi", "mom", "percent"
    ),
    ("cpi", "yoy"): LongbridgeIndicatorSpec(
        "30771871", "cpi", "yoy", "percent"
    ),
    ("core_cpi", "mom"): LongbridgeIndicatorSpec(
        "30771844", "core_cpi", "mom", "percent"
    ),
    ("core_cpi", "yoy"): LongbridgeIndicatorSpec(
        "30771867", "core_cpi", "yoy", "percent"
    ),

    # ---------- PPI ----------
    ("ppi", "mom"): LongbridgeIndicatorSpec(
        "30772016", "ppi", "mom", "percent"
    ),
    ("ppi", "yoy"): LongbridgeIndicatorSpec(
        "30771924", "ppi", "yoy", "percent"
    ),
    ("core_ppi", "mom"): LongbridgeIndicatorSpec(
        "30771828", "core_ppi", "mom", "percent"
    ),
    ("core_ppi", "yoy"): LongbridgeIndicatorSpec(
        "30771801", "core_ppi", "yoy", "percent"
    ),

    # ---------- PCE ----------
    ("pce", "mom"): LongbridgeIndicatorSpec(
        "30771712", "pce", "mom", "percent"
    ),
    ("pce", "yoy"): LongbridgeIndicatorSpec(
        "30771701", "pce", "yoy", "percent"
    ),
    ("core_pce", "mom"): LongbridgeIndicatorSpec(
        "30771661", "core_pce", "mom", "percent"
    ),
    ("core_pce", "yoy"): LongbridgeIndicatorSpec(
        "30771724", "core_pce", "yoy", "percent"
    ),

    # ---------- Employment ----------
    ("nonfarm_payrolls", "monthly_change"):
        LongbridgeIndicatorSpec(
            code="30771890",
            indicator="nonfarm_payrolls",
            measure="monthly_change",
            unit="jobs",
            scale=Decimal("1000"),
        ),

    ("unemployment_rate", "level"):
        LongbridgeIndicatorSpec(
            "30771865",
            "unemployment_rate",
            "level",
            "percent",
        ),

    ("average_hourly_earnings", "mom"):
        LongbridgeIndicatorSpec(
            "30771703",
            "average_hourly_earnings",
            "mom",
            "percent",
        ),

    # ---------- Weekly Claims ----------
    ("initial_claims", "level"): LongbridgeIndicatorSpec(
        code="30771888",
        indicator="initial_claims",
        measure="level",
        unit="persons",
        scale=Decimal("1000"),
        frequency="weekly",
    ),

    ("continuing_claims", "level"): LongbridgeIndicatorSpec(
        code="30771803",
        indicator="continuing_claims",
        measure="level",
        unit="persons",
        scale=Decimal("1000000"),
        frequency="weekly",
    ),

    ("initial_claims_4w_avg", "level"):
        LongbridgeIndicatorSpec(
            code="30771904",
            indicator="initial_claims_4w_avg",
            measure="level",
            unit="persons",
            scale=Decimal("1000"),
            frequency="weekly",
        ),
}

def normalize_value(
    raw_value: str | None,
    spec: LongbridgeIndicatorSpec,
) -> Decimal | None:
    """标准化 Actual、Previous 或 Forecast。

    缺失值返回 None。
    无法解析的非空值抛出 ValueError。
    """

    if raw_value is None:
        return None

    raw = raw_value.strip().replace(",", "")

    if raw in {"", "-", "--"}:
        return None

    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid Longbridge value: {raw_value!r}"
        ) from exc

    if not value.is_finite():
        raise ValueError(
            f"Non-finite Longbridge value: {raw_value!r}"
        )

    normalized = value * spec.scale

    # 人数、岗位数在本项目中使用整数单位。
    if spec.unit in {"persons", "jobs"}:
        if normalized != normalized.to_integral_value():
            raise ValueError(
                f"Non-integer count: {raw_value!r}"
            )

    return normalized
