from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class FedPolicyEvent(BaseModel):
    """一次 FOMC 会议正式公布的目标利率决议。

    meeting_date:
        会议结束日期。

    target_lower / target_upper:
        本次决议公布的联邦基金目标利率区间。
        单位是百分比，例如 3.50 表示 3.50%。

    released_at:
        本次利率决议的正式公布时间。

    不负责：
        - 判断本次是加息、降息还是维持；
        - 保存未来利率预测；
        - 预测下一次会议的决定。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_date: date
    target_lower: Decimal
    target_upper: Decimal
    released_at: AwareDatetime
    source: str
    source_url: str | None = None

    @model_validator(mode="after")
    def validate_target_range(self):
        """在数据进入系统时校验目标区间。"""
        if self.target_lower > self.target_upper:
            raise ValueError("target_lower cannot exceed target_upper")
        return self


ProjectionYear = int | Literal["longer_run"]


class FedDotProjection(BaseModel):
    """点阵图中某一预测年度的政策利率分布。

    target_year:
        预测对应的日历年，或长期水平。

    dots:
        该年度所有参与者的匿名预测值。

        必须保留重复数值，因为多个参与者
        可能给出完全相同的预测。

    published_median:
        官方公布的中位数。
        若数据源没有提供，可以暂时为 None。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_year: ProjectionYear
    dots: list[Decimal]
    published_median: Decimal | None = None


class FedDotProjectionRelease(BaseModel):
    """某次 FOMC 会议发布的一套 SEP 利率预测。

    一次发布包含多个预测年度的 FedDotProjection。
    整套点阵图共用会议日期、发布时间和来源。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_date: date
    released_at: AwareDatetime
    projections: list[FedDotProjection]
    source: str
    source_url: str | None = None


class FedTargetRange(BaseModel):
    """某个日期开始生效的联邦基金目标区间。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effective_date: date
    target_lower: Decimal
    target_upper: Decimal
    source: Literal["fred"] = "fred"


class FedMedianProjection(BaseModel):
    """SEP 中某个目标年份或长期的联邦基金利率中位数预测。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_year: ProjectionYear
    median: Decimal


class FedMedianProjectionRelease(BaseModel):
    """某个历史时点可获得的一版 SEP。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vintage_date: date

    # 这一版数据对应的 FRED vintage。
    projections: list[FedMedianProjection]
    source: Literal["fred"] = "fred"


@dataclass(frozen=True)
class FedPolicySnapshot:
    current: FedTargetRange
    previous: FedTargetRange | None
    lower_change_bps: Decimal | None
    upper_change_bps: Decimal | None
