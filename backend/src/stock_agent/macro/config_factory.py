"""组装真实 MacroSnapshotBuilder。"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from longbridge.openapi import Config, FundamentalContext

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


ROOT = Path(__file__).resolve().parents[4]
LONGBRIDGE_TIMEZONE = ZoneInfo("Asia/Shanghai")


def build_macro_snapshot_builder() -> MacroSnapshotBuilder:
    """从环境变量创建真实宏观 Provider 及 Builder。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)

    client = httpx.Client(timeout=60.0)
    fred = FredProvider(
        client=client,
        api_key=os.environ["FRED_API_KEY"],
    )
    te_api_key = os.environ.get(
        "TRADING_ECONOMICS_API_KEY",
        "",
    ).strip()
    return MacroSnapshotBuilder(
        bls=BLSProvider(client),
        bea=BEAPCEProvider(
            client=client,
            api_key=os.environ["BEA_API_KEY"],
        ),
        consensus=(
            TradingEconomicsConsensusProvider(
                client,
                api_key=te_api_key,
            )
            if te_api_key
            else None
        ),
        fred=fred,
        fed=FedDataProvider(fred),
        treasury=TreasuryRatesProvider(fred),
        claims=WeeklyClaimsProvider(fred),
        longbridge_macro=LongbridgeMacroProvider(
            FundamentalContext(Config.from_apikey_env())
        ),
        longbridge_vendor_timezone=LONGBRIDGE_TIMEZONE,
    )
