"""Day26 真实长桥历史分钟行情验收。"""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from stock_agent.market.intraday import HistoricalMinuteBarsRequest
from stock_agent.market.intraday_coverage import inspect_intraday_coverage
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)
from stock_agent.quality.intraday import validate_intraday_bars


ROOT = Path(__file__).resolve().parents[1]
NEW_YORK = ZoneInfo("America/New_York")


def main() -> None:
    load_dotenv(ROOT / "backend" / ".env", override=False)
    start_at = datetime(2026, 9, 25, 4, tzinfo=NEW_YORK)
    end_at = datetime(2026, 9, 25, 20, tzinfo=NEW_YORK)
    as_of = datetime.now(timezone.utc)
    request = HistoricalMinuteBarsRequest(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        as_of=as_of,
    )

    bars = build_longbridge_market_provider().get_intraday_bars(
        "NVDA",
        start_at=start_at,
        end_at=end_at,
        as_of=as_of,
    )
    quality = validate_intraday_bars(
        request=request,
        bars=bars,
        required_sessions=["regular"],
    )
    coverage = inspect_intraday_coverage(
        request=request,
        bars=bars,
        required_sessions={"pre", "regular", "post", "overnight"},
    )

    print("source= longbridge")
    print("bars=", len(bars))
    print("quality_status=", quality.status)
    print("quality_issues=", [issue.code for issue in quality.issues])
    print("first_bar_at=", coverage.first_bar_at)
    print("last_bar_end_at=", coverage.last_bar_end_at)
    print("session_counts=", coverage.observed_counts)
    print("coverage_status=", coverage.status)

    assert bars
    assert quality.status == "usable"
    assert bars == sorted(bars, key=lambda bar: bar.start_at)

    print("Day26 Longbridge intraday verification passed.")


if __name__ == "__main__":
    main()
