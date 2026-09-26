"""Day24 宏观快照真实 API 端到端验收。"""

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import httpx
from longbridge.openapi import Config, FundamentalContext
from zoneinfo import ZoneInfo

from stock_agent.macro.builder import MacroSnapshotBuilder
from stock_agent.macro.providers.bea import BEAPCEProvider
from stock_agent.macro.providers.bls import BLSProvider
from stock_agent.macro.providers.fed import FedDataProvider
from stock_agent.macro.providers.fred import FredProvider
from stock_agent.macro.providers.fred_claims import WeeklyClaimsProvider
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroProvider,
)
from stock_agent.macro.providers.trading_economics import (
    TradingEconomicsConsensusProvider,
)
from stock_agent.macro.providers.treasury import TreasuryRatesProvider


ROOT = Path(__file__).resolve().parents[1]
LONGBRIDGE_TIMEZONE = ZoneInfo("Asia/Shanghai")
EXPECTED_RELEASES = {
    "cpi",
    "ppi",
    "pce",
    "employment_situation",
    "weekly_claims",
}


def main() -> None:
    """使用真实 Provider 构建并检查完整 MacroSnapshot。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)

    fred_api_key = os.environ["FRED_API_KEY"]
    bea_api_key = os.environ["BEA_API_KEY"]
    te_api_key = os.environ.get("TRADING_ECONOMICS_API_KEY", "").strip()
    longbridge = LongbridgeMacroProvider(
        FundamentalContext(Config.from_apikey_env())
    )

    with httpx.Client(timeout=60.0) as client:
        fred = FredProvider(client=client, api_key=fred_api_key)
        consensus = (
            TradingEconomicsConsensusProvider(client, api_key=te_api_key)
            if te_api_key
            else None
        )
        builder = MacroSnapshotBuilder(
            bls=BLSProvider(client),
            bea=BEAPCEProvider(client=client, api_key=bea_api_key),
            consensus=consensus,
            fred=fred,
            fed=FedDataProvider(fred),
            treasury=TreasuryRatesProvider(fred),
            claims=WeeklyClaimsProvider(fred),
            longbridge_macro=longbridge,
            longbridge_vendor_timezone=LONGBRIDGE_TIMEZONE,
        )
        snapshot = builder.build_latest(
            as_of=datetime.now(timezone.utc),
        )

    release_types = {
        release.release_type for release in snapshot.recent_releases
    }
    missing = EXPECTED_RELEASES - release_types
    assert not missing, f"Missing releases: {sorted(missing)}"
    assert snapshot.fed_policy is not None
    assert snapshot.fed_projections
    assert snapshot.treasury is not None

    for release in snapshot.recent_releases:
        assert release.metrics
        assert release.release_date < snapshot.as_of.date()
        assert all(
            metric.release_date == release.release_date
            for metric in release.metrics
        )
        assert all(
            metric.consensus_pit_verified or metric.surprise is None
            for metric in release.metrics
        )
        for metric in release.metrics:
            if (
                metric.source == "longbridge"
                and metric.consensus is not None
            ):
                assert metric.estimated_surprise == (
                    metric.actual - metric.consensus
                )
                assert metric.consensus_source == "longbridge"
                assert metric.forecast_as_of is None
                assert metric.consensus_pit_verified is False
                assert metric.surprise is None
        print(
            release.release_id,
            "metrics=",
            len(release.metrics),
            "scheduled_release_at=",
            release.scheduled_release_at,
        )

    print("fed_policy=", snapshot.fed_policy.current)
    print("fed_projections=", len(snapshot.fed_projections))
    print("treasury_date=", snapshot.treasury.observation_date)
    print("warnings=", snapshot.warnings)
    print("Day24 macro snapshot verification passed.")


if __name__ == "__main__":
    main()
