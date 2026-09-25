from datetime import date, timedelta
from decimal import Decimal

from stock_agent.macro.models.fed import FedMedianProjection, FedTargetRange
from stock_agent.macro.providers.fred import FredProvider


FED_TARGET_LOWER = "DFEDTARL"
FED_TARGET_UPPER = "DFEDTARU"

FED_PROJECTION_MEDIAN = "FEDTARMD"
FED_PROJECTION_LONG_RUN = "FEDTARMDLR"


class FedDataProvider:
    """把 FRED 原始序列转换为 Fed 领域数据。"""

    def __init__(self, fred: FredProvider) -> None:
        self.fred = fred

    # 目标利率有效值
    def get_target_ranges(
        self,
        *,
        as_of: date,
        lookback_days: int = 365,
    ) -> list[FedTargetRange]:
        """获取截至 as_of 生效的目标利率区间变化。"""

        start = as_of - timedelta(days=lookback_days)
        lower_points = self.fred.get_observations(
            FED_TARGET_LOWER,
            observation_start=start,
            observation_end=as_of,
        )
        upper_points = self.fred.get_observations(
            FED_TARGET_UPPER,
            observation_start=start,
            observation_end=as_of,
        )

        lower = {point.period: point.value for point in lower_points}
        upper = {point.period: point.value for point in upper_points}
        common_dates = sorted(lower.keys() & upper.keys())

        ranges: list[FedTargetRange] = []
        previous_range: tuple[Decimal, Decimal] | None = None

        for current_date in common_dates:
            current_range = (lower[current_date], upper[current_date])
            if current_range == previous_range:
                continue

            ranges.append(
                FedTargetRange(
                    effective_date=current_date,
                    target_lower=current_range[0],
                    target_upper=current_range[1],
                )
            )
            previous_range = current_range

        return ranges

    # 某历史时点能够看到的 SEP 预测
    def get_current_projections(
        self,
        *,
        as_of: date,
    ) -> list[FedMedianProjection]:
        """获取某历史日期能够看到的 SEP 中位数预测。"""

        yearly = self.fred.get_observations(
            FED_PROJECTION_MEDIAN,
            realtime_start=as_of,
            realtime_end=as_of,
        )
        longer_run = self.fred.get_observations(
            FED_PROJECTION_LONG_RUN,
            observation_end=as_of,
            realtime_start=as_of,
            realtime_end=as_of,
            sort_order="desc",
            limit=1,
        )

        projections = [
            FedMedianProjection(
                target_year=point.period.year,
                median=point.value,
            )
            for point in yearly
        ]

        if longer_run:
            projections.append(
                FedMedianProjection(
                    target_year="longer_run",
                    median=longer_run[0].value,
                )
            )

        return projections
