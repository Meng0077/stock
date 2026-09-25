from datetime import date, timedelta

import httpx

from stock_agent.macro.calculations.claims import calculate_weekly_claims
from stock_agent.macro.providers.fred_claims import (
    WeeklyClaimsProvider,
    CLAIMS_SERIES,
)

def main() -> None:
    """获取并展示真实的周频失业金申领数据。"""

    start_date = date.today() - timedelta(days=90)

    client = httpx.Client(timeout=60.0)
    provider = WeeklyClaimsProvider(client)
    
    for indicator, series_id in CLAIMS_SERIES.items():
        points = provider.fetch_series(
            series_id,
            start_date=start_date,
        )

        reading = calculate_weekly_claims(
            indicator=indicator,
            points=points,
        )

        print(indicator, reading)


if __name__ == "__main__":
    main()
