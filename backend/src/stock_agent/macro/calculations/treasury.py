from datetime import date
from decimal import Decimal
from typing import cast

from stock_agent.macro.models.treasury import (
    TREASURY_TENORS,
    TreasurySnapshot,
    TreasuryTenor,
    TreasuryYield,
)


def build_treasury_snapshot(
    *,
    observations: list[TreasuryYield],
    as_of: date,
    max_age_days: int = 7,
) -> TreasurySnapshot | None:
    """根据四个期限的收益率构建完整曲线快照。

    输入：
        observations：
            已获取的不同日期、不同期限收益率。

        as_of：
            本次查询允许使用的最晚观测日期。

        max_age_days：
            超过多少个自然日就标记为过期。

    输出：
        最新完整曲线、上一期完整曲线对应日期、
        各期限日变化，以及两项期限利差。

    约束：
        只拼接同一天的四个期限。
        不用其他日期的数据填补缺失期限。
        不负责 API 请求与实际发布时间校验。
    """

    # 1. 按观测日期和期限组织数据。
    by_date: dict[date, dict[TreasuryTenor, Decimal]] = {}

    for item in observations:
        if item.observation_date > as_of:
            continue

        daily = by_date.setdefault(item.observation_date, {})

        # 相同日期和期限不允许出现冲突数据。
        if item.tenor in daily:
            raise ValueError(
                "Duplicate Treasury observation: "
                f"{item.observation_date}, {item.tenor}"
            )
        daily[item.tenor] = item.yield_pct

    required = set(TREASURY_TENORS)

    # 2. 找出四个期限都有数据的日期。
    complete_dates = sorted(
        observation_date
        for observation_date, daily in by_date.items()
        if set(daily) == required
    )
    if not complete_dates:
        return None

    # 3. 使用最新的完整观测日期。
    current_date = complete_dates[-1]
    current = by_date[current_date]

    # 4. 找到上一期完整曲线。
    previous_date = complete_dates[-2] if len(complete_dates) >= 2 else None
    daily_change_bps = None

    if previous_date is not None:
        previous = by_date[previous_date]

        # 收益率单位是百分比：
        # 0.01 个百分点 = 1 bp。
        daily_change_bps = {
            tenor: (current[tenor] - previous[tenor]) * Decimal("100")
            for tenor in TREASURY_TENORS
        }

    # 5. 计算期限利差，单位为 bp。
    spread_10y_2y = (current["10y"] - current["2y"]) * Decimal("100")
    spread_10y_3m = (current["10y"] - current["3m"]) * Decimal("100")

    # 6. 标记数据是否过期。
    age_days = (as_of - current_date).days
    return TreasurySnapshot(
        observation_date=current_date,
        yields={tenor: current[tenor] for tenor in TREASURY_TENORS},
        previous_observation_date=previous_date,
        daily_change_bps=cast(
            dict[TreasuryTenor, Decimal] | None,
            daily_change_bps,
        ),
        spread_10y_2y_bps=spread_10y_2y,
        spread_10y_3m_bps=spread_10y_3m,
        age_days=age_days,
        is_stale=age_days > max_age_days,
    )
