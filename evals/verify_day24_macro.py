"""Day24 CPI/PPI 与官方发布日期在线验收。"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
import httpx

from stock_agent.macro.calculations.inflation import (
    InflationIndicator,
    build_inflation_metrics,
    calculate_inflation_reading,
)
from stock_agent.macro.models.metric import ConsensusObservation
from stock_agent.macro.models.release import MacroReleaseType
from stock_agent.macro.providers.bls import BLSProvider
from stock_agent.macro.providers.fred import FredProvider
from stock_agent.macro.providers.trading_economics import (
    TradingEconomicsConsensusProvider,
)
from stock_agent.macro.release_builders import (
    BLS_INFLATION_RELEASE_CONFIG,
    INFLATION_SERIES,
    MACRO_RELEASE_SERIES,
    build_macro_release,
    get_latest_release_date,
    resolve_scheduled_release_at,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """使用真实 BLS/FRED API 验收最近一次 CPI 和 PPI 发布。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)

    client = httpx.Client(timeout=60.0)

    fred = FredProvider(
        client=client,
        api_key=os.environ["FRED_API_KEY"],
    )
    bls = BLSProvider(client)

    te_api_key = os.environ.get("TRADING_ECONOMICS_API_KEY")
    consensus_provider = (
        TradingEconomicsConsensusProvider(
            client,
            api_key=te_api_key,
        )
        if te_api_key
        else None
    )

    as_of = datetime.now(timezone.utc)

    for release_type in ("cpi", "ppi"):
        release_date = get_latest_release_date(
            fred=fred,
            series_id=MACRO_RELEASE_SERIES[
                cast(MacroReleaseType, release_type)
            ],
            as_of=as_of.date(),
        )

        assert release_date is not None

        forecasts: list[ConsensusObservation] = []

        if consensus_provider is not None:
            forecasts = consensus_provider.get_consensus(
                start_date=release_date,
                end_date=release_date,
            )

        metrics = []

        for raw_indicator in BLS_INFLATION_RELEASE_CONFIG[
            release_type
        ]["indicators"]:
            indicator = cast(InflationIndicator, raw_indicator)
            sa_series, nsa_series = INFLATION_SERIES[indicator]
            data = bls.fetch_series([sa_series, nsa_series])

            reading = calculate_inflation_reading(
                sa_points=data.get(sa_series, []),
                nsa_points=data.get(nsa_series, []),
            )

            assert reading is not None

            calculated = build_inflation_metrics(
                indicator=indicator,
                reading=reading,
                forecasts=forecasts,
                release_date=release_date,
            )
            metrics.extend(calculated.values())

        scheduled_release_at = resolve_scheduled_release_at(
            metrics=metrics,
            forecasts=forecasts,
        )

        release = build_macro_release(
            release_type=cast(MacroReleaseType, release_type),
            release_date=release_date,
            metrics=metrics,
            release_date_source="fred",
            scheduled_release_at=scheduled_release_at,
            schedule_source=(
                "trading_economics"
                if scheduled_release_at is not None
                else None
            ),
            period_binding="latest_assumed",
        )

        assert len(release.metrics) == 4
        assert release.released_at is None
        assert all(
            metric.release_date == release.release_date
            for metric in release.metrics
        )
        assert all(
            metric.consensus is not None
            or metric.surprise is None
            for metric in release.metrics
        )

        print(
            release.release_id,
            "metrics=",
            len(release.metrics),
            "scheduled_release_at=",
            release.scheduled_release_at,
        )

    print("Day24 macro release verification passed.")


if __name__ == "__main__":
    main()
