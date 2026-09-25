"""通过真实 FRED API 检查最新收益率曲线。"""

import os
from datetime import date
from pathlib import Path

import httpx

from stock_agent.macro.calculations.treasury import build_treasury_snapshot
from stock_agent.macro.models.treasury import TREASURY_TENORS
from stock_agent.macro.providers.fred import FredProvider
from stock_agent.macro.providers.treasury import (
    TreasuryRatesProvider,
)

ROOT = Path(__file__).resolve().parents[1]
from dotenv import load_dotenv

def main() -> None:
    """获取并打印四个期限和期限利差。"""
    
    load_dotenv(ROOT / "backend" / ".env", override=False)
    
    FRED_API_KEY = os.environ["FRED_API_KEY"]

    client = httpx.Client(timeout=60.0)
    fred = FredProvider(
        client=client,
        api_key=FRED_API_KEY,
    )

    provider = TreasuryRatesProvider(fred)

    observations = provider.get_yields(
        list(TREASURY_TENORS),
        as_of=date.today(),
    )
    snapshot = build_treasury_snapshot(
        observations=observations,
        as_of=date.today(),
    )

    if snapshot is None:
        print("No complete Treasury curve")
        return

    print("Observation date:", snapshot.observation_date)
    print("Yields:", snapshot.yields)
    print("Daily changes:", snapshot.daily_change_bps)
    print("10Y - 2Y:", snapshot.spread_10y_2y_bps, "bp")
    print("10Y - 3M:", snapshot.spread_10y_3m_bps, "bp")
    print("Is stale:", snapshot.is_stale)


if __name__ == "__main__":
    main()
