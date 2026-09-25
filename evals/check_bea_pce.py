
"""获取真实 PCE / Core PCE 并计算月度、年度变化率。"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import httpx

from stock_agent.macro.providers.bea import (
    BEAPCEProvider,
)
from stock_agent.macro.calculations.inflation import (
    calculate_pce_reading,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """获取最近三年的月度 PCE 指数并输出变化率。"""
    load_dotenv(ROOT / "backend" / ".env", override=False)

    api_key = os.environ["BEA_API_KEY"]

    current_year = date.today().year

    client = httpx.Client(timeout=60.0)
    provider = BEAPCEProvider(
        client=client,
        api_key=api_key,
    )

    data = provider.fetch_indexes(
        years=[
            current_year - 2,
            current_year - 1,
            current_year,
        ]
    )

    for indicator in ("pce", "core_pce"):
        reading = calculate_pce_reading(
            data[indicator]
        )

        print(f"\n=== {indicator.upper()} ===")

        if reading is None:
            print("Insufficient data")
            continue

        print("Period:", reading.period)
        print("MoM:", reading.mom_actual_pct)
        print("Previous MoM:", reading.mom_previous_pct)
        print("YoY:", reading.yoy_actual_pct)
        print("Previous YoY:", reading.yoy_previous_pct)


if __name__ == "__main__":
    main()
