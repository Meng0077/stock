"""获取真实 BLS 就业数据，检查三个就业指标的计算结果。"""

import httpx

from stock_agent.macro.providers.bls import BLSProvider
from stock_agent.macro.calculations.employment import (
    calculate_nonfarm_payrolls,
    calculate_unemployment_rate,
    calculate_average_hourly_earnings,
)


EMPLOYMENT_SERIES = {
    # 全部非农就业人数，季调后，单位为千人。
    "nonfarm_payrolls": "CES0000000001",

    # 美国失业率，季调后，单位为百分比。
    "unemployment_rate": "LNS14000000",

    # 私营非农平均时薪，季调后，单位为美元/小时。
    "average_hourly_earnings": "CES0500000003",
}


def main() -> None:
    """获取真实就业数据，分别计算并输出三个指标。"""

    with httpx.Client(timeout=20.0) as client:
        provider = BLSProvider(client)

        data = provider.fetch_series(
            list(EMPLOYMENT_SERIES.values())
        )

    # 1. 非农就业：计算新增岗位。
    payrolls = calculate_nonfarm_payrolls(
        data.get(
            EMPLOYMENT_SERIES["nonfarm_payrolls"],
            [],
        )
    )

    print("\n=== Nonfarm Payrolls ===")

    if payrolls is None:
        print("Insufficient data")
    else:
        print("Period:", payrolls.period)
        print("Actual:", payrolls.actual, "jobs")
        print("Previous:", payrolls.previous, "jobs")

    # 2. 失业率：读取本月和上月失业率。
    unemployment = calculate_unemployment_rate(
        data.get(
            EMPLOYMENT_SERIES["unemployment_rate"],
            [],
        )
    )

    print("\n=== Unemployment Rate ===")

    if unemployment is None:
        print("Insufficient data")
    else:
        print("Period:", unemployment.period)
        print("Actual:", unemployment.actual, "%")
        print("Previous:", unemployment.previous, "%")

    # 3. 平均时薪：水平、环比、同比。
    earnings = calculate_average_hourly_earnings(
        data.get(
            EMPLOYMENT_SERIES["average_hourly_earnings"],
            [],
        )
    )

    print("\n=== Average Hourly Earnings ===")

    for metric in earnings:
        print(
            "Period:", metric.period,
            "| Measure:", metric.measure,
            "| Actual:", metric.actual,
            "| Previous:", metric.previous,
            "| Unit:", metric.unit,
        )


if __name__ == "__main__":
    main()
