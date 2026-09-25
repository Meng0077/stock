from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict


TreasuryTenor = Literal["3m", "2y", "10y", "30y"]

TREASURY_TENORS: tuple[TreasuryTenor, ...] = (
    "3m",
    "2y",
    "10y",
    "30y",
)


class TreasuryYield(BaseModel):
    """某个日期、某个期限的美债收益率。

    observation_date：
        收益率对应的市场观测日期。

    yield_pct：
        百分比数值，例如 4.25 表示 4.25%，
        而不是小数 0.0425。

    released_at：
        经核实的实际发布时间。
        FRED 普通观测记录不能直接提供准确的
        逐条发布时间，所以目前为 None。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_date: date
    tenor: TreasuryTenor
    yield_pct: Decimal

    # 明确使用名义票面收益率曲线。
    curve_type: Literal["nominal_cmt_h15"] = "nominal_cmt_h15"
    released_at: AwareDatetime | None = None
    source: str = "fred_h15"
    source_url: str | None = None


@dataclass(frozen=True)
class TreasurySnapshot:
    """某一观测日期的完整收益率曲线快照。

    yields：
        四个期限的收益率，单位为百分比。

    daily_change_bps：
        与上一个完整观测日相比的变化，单位 bp。
        如果缺少上一期完整曲线，则为 None。

    spread_10y_2y_bps：
        10 年收益率减去 2 年收益率。

    spread_10y_3m_bps：
        10 年收益率减去 3 个月收益率。

    age_days：
        观测日期距离查询日期的自然日数。
        用于后续数据新鲜度校验。
    """

    observation_date: date
    yields: dict[TreasuryTenor, Decimal]
    previous_observation_date: date | None
    daily_change_bps: dict[TreasuryTenor, Decimal] | None
    spread_10y_2y_bps: Decimal
    spread_10y_3m_bps: Decimal
    age_days: int
    is_stale: bool
