from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict


EconomicIndicator = Literal[
    # 通胀
    "cpi",
    "core_cpi",
    "ppi",
    "core_ppi",
    "pce",
    "core_pce",
    # 就业
    "initial_claims",
    "continuing_claims",
    "initial_claims_4w_avg",
    "nonfarm_payrolls",
    "unemployment_rate",
    "average_hourly_earnings",
]

EconomicMeasure = Literal[
    "mom",             # 环比百分比
    "yoy",             # 同比百分比
    "level",           # 绝对数值
    "monthly_change",  # 月度变化数量
]

EconomicUnit = Literal[
    "percent",
    "persons",
    "jobs",
    "usd_per_hour",
]

SeasonalAdjustment = Literal[
    "sa",              # 季节性调整
    "nsa",             # 未经季节性调整
    "not_applicable",
]


class EconomicObservation(BaseModel):
    """某个经济指标在某次公布中的一个数值版本。

    一条 Observation 只记录一个 indicator + measure。
    例如 CPI YoY 和 CPI MoM 是两条记录。

    数据修订时保留原记录，并创建新记录；
    不直接覆盖旧值。

    本模型只表示官方经济数据，
    不包含市场 consensus 或 surprise。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    indicator: EconomicIndicator
    measure: EconomicMeasure
    unit: EconomicUnit

    # 统计区间：同时兼容月度和周度指标。
    frequency: Literal["monthly", "weekly"]
    period_start: date
    period_end: date
    seasonal_adjustment: SeasonalAdjustment

    # 例如 Decimal("2.8") 代表 2.8%。
    value: Decimal

    # 该数值版本的正式公布时间。
    released_at: AwareDatetime

    # 数据来源与追溯信息。
    source: str
    source_url: str | None = None


@dataclass(frozen=True)
class ConsensusObservation:
    """某次经济数据发布对应的市场一致预期。

    period:
        指标对应的统计月份。

    scheduled_release_at:
        经济日历提供的公布时间，并不保证
        未来公布时间绝对不会调整。

    consensus:
        市场一致预期，而不是供应商自己的预测。
    """

    indicator: EconomicIndicator
    measure: EconomicMeasure
    period: date
    scheduled_release_at: datetime
    consensus: Decimal

    # 仅当供应商支持可信的历史快照时才填写。
    forecast_as_of: datetime | None
    source: str
    event_id: str


PITStatus = Literal[
    "verified",       # 能证明当前 actual 在 as_of 时已经可见
    "date_verified",  # 能证明截至 as_of 所在日期的数据版本
    "unverified",     # 当前值可能包含后续修订
]


class MacroMetricSnapshot(BaseModel):
    """Agent 最终消费的一项宏观经济指标。

    这是业务层统一结构，不直接对应某个供应商 API。

    actual:
        当前统计期实际值。

    previous:
        上一个可比统计期的值。
        例如：
        - CPI MoM：上个月的 MoM
        - 非农：上个月新增就业
        - 失业率：上个月失业率

    consensus:
        市场一致预期。
        无可靠预期数据时为 None。

    surprise:
        actual - consensus。
        单位与 actual/consensus 一致。


    release_date:
        官方发布日期，只精确到日期时填写。

    released_at:
        经核实的正式发布时间。
        无法确认时不要自行构造。

    forecast_as_of:
        如果供应商能证明 Forecast 属于某历史快照，
        记录该历史时点，否则为 None。

    consensus_pit_verified:
        是否能确认 consensus 在正式公布之前已经存在。

    surprise_is_estimated:
        actual 是否由底层指数计算得到，而不是直接读取
        官方公布的百分比 headline。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    indicator: EconomicIndicator
    measure: EconomicMeasure
    unit: EconomicUnit
    period: date
    actual: Decimal
    previous: Decimal | None = None
    consensus: Decimal | None = None
    surprise: Decimal | None = None

    estimated_surprise: Decimal | None = None
    consensus_source: str | None = None

    release_date: date | None = None
    released_at: datetime | None = None
    forecast_as_of: datetime | None = None
    surprise_is_estimated: bool = False
    source: str
    actual_pit_status: PITStatus = "unverified"
    consensus_pit_verified: bool = False


TemporalDecision = Literal[
    "usable",
    "usable_with_warning",
    "reject",
]


@dataclass(frozen=True)
class TemporalValidation:
    """宏观数据的时间有效性检查结果。

    decision:
        usable:
            可以安全使用。

        usable_with_warning:
            可以用于普通研究，但 PIT 证据不完整。

        reject:
            会造成明确的未来数据泄漏，必须拒绝。

    reason:
        机器可读原因，便于 Agent / 测试判断。
    """

    decision: TemporalDecision
    reason: str
