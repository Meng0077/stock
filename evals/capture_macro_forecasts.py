"""采集下一次宏观发布的长桥 Forecast 快照。"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from longbridge.openapi import Config, FundamentalContext

from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.forecast_capture import (
    append_forecast_snapshot,
    capture_next_forecasts,
)
from stock_agent.macro.models.release import MacroReleaseType
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroProvider,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOTS_PATH = (
    ROOT / "evals" / "results" / "macro_forecasts.jsonl"
)
LONGBRIDGE_TIMEZONE = ZoneInfo("Asia/Shanghai")
RELEASE_TYPES: tuple[MacroReleaseType, ...] = (
    "cpi",
    "ppi",
    "pce",
    "employment_situation",
    "weekly_claims",
)


def main() -> None:
    """执行一次采集；由外部调度器定期调用。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)
    path = Path(
        os.environ.get(
            "MACRO_FORECAST_SNAPSHOTS_PATH",
            DEFAULT_SNAPSHOTS_PATH,
        )
    )
    macro = LongbridgeMacroProvider(
        FundamentalContext(Config.from_apikey_env())
    )
    warnings: list[str] = []
    captured = 0

    for release_type in RELEASE_TYPES:
        try:
            snapshot = capture_next_forecasts(
                macro=macro,
                release_type=release_type,
                vendor_timezone=LONGBRIDGE_TIMEZONE,
                warnings=warnings,
            )
        except MacroDataProviderError:
            warnings.append(f"{release_type}_capture_failed")
            continue

        if snapshot is None:
            continue

        append_forecast_snapshot(snapshot, path)
        captured += 1
        print(
            release_type,
            "release_date=",
            snapshot.release_date,
            "captured_at=",
            snapshot.captured_at.isoformat(),
            "forecasts=",
            len(snapshot.forecasts),
        )

    print("saved=", captured, "path=", path)
    print("warnings=", warnings)


if __name__ == "__main__":
    main()
