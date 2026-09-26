import os
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

from stock_agent.macro.calculations.claims import calculate_weekly_claims
from stock_agent.macro.providers.fred import FredProvider
from stock_agent.macro.providers.fred_claims import (
    WeeklyClaimsProvider,
    CLAIMS_SERIES,
)


ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    """获取并展示真实的周频失业金申领数据。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)

    as_of = date.today()
    start_date = as_of - timedelta(days=90)

    with httpx.Client(timeout=60.0) as client:
        fred = FredProvider(client, api_key=os.environ["FRED_API_KEY"])
        provider = WeeklyClaimsProvider(fred)

        for indicator, series_id in CLAIMS_SERIES.items():
            points = provider.fetch_series(
                series_id,
                start_date=start_date,
                as_of=as_of,
            )

            reading = calculate_weekly_claims(
                indicator=indicator,
                points=points,
            )

            print(indicator, reading)


if __name__ == "__main__":
    main()
