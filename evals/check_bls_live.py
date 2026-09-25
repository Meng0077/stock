# backend/examples/check_bls_live.py

import httpx

from stock_agent.macro.calculations.inflation import (
    calculate_inflation_reading,
)
from stock_agent.macro.providers.bls import BLSProvider


INFLATION_SERIES = {
    "cpi": (
        "CUSR0000SA0",
        "CUUR0000SA0",
    ),
    "core_cpi": (
        "CUSR0000SA0L1E",
        "CUUR0000SA0L1E",
    ),
    "ppi": (
        "WPSFD4",
        "WPUFD4",
    ),
    "core_ppi": (
        "WPSFD49104",
        "WPUFD49104",
    ),
}


def main() -> None:
    """获取真实 BLS 指数并输出四组通胀指标。"""

    series_ids = [
        series_id
        for pair in INFLATION_SERIES.values()
        for series_id in pair
    ]

    with httpx.Client(timeout=20.0) as client:
        provider = BLSProvider(client)
        data = provider.fetch_series(series_ids)

    for indicator, (sa_id, nsa_id) in (
        INFLATION_SERIES.items()
    ):
        reading = calculate_inflation_reading(
            sa_points=data.get(sa_id, []),
            nsa_points=data.get(nsa_id, []),
        )

        if reading is None:
            print(f"{indicator}: insufficient data")
            continue

        print(
            indicator,
            reading.period,
            "MoM:",
            reading.mom_actual_pct,
            "Previous MoM:",
            reading.mom_previous_pct,
            "YoY:",
            reading.yoy_actual_pct,
            "Previous YoY:",
            reading.yoy_previous_pct,
        )


if __name__ == "__main__":
    main()
