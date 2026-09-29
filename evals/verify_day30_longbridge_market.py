"""Day30 Step 1：真实 CPI 日期的长桥历史行情检查。

只读行情 API，不调用模型，不提交交易订单。

运行：
PYTHONPATH=backend/src backend/.venv/bin/python \
    evals/verify_day30_longbridge_market.py
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.intraday import HistoricalMinuteBarsRequest
from stock_agent.market.intraday_coverage import inspect_intraday_coverage
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)
from stock_agent.market_reaction.close_data import get_target_daily_bar
from stock_agent.market_reaction.trading_calendar import resolve_close_at
from stock_agent.quality.intraday import validate_intraday_bars


ROOT = Path(__file__).resolve().parents[1]
EASTERN = ZoneInfo("America/New_York")

SYMBOLS = ("NVDA", "QQQ", "SOXL")

# 2026-09-11：美国 8 月 CPI 的官方计划发布时间。
# 此处仅用于定位行情查询区间，
# 尚不代表已独立核实实际发布时间。
SCHEDULED_AT = datetime(
    2026, 9, 11, 8, 30,
    tzinfo=EASTERN,
)

# 从计划发布时间前 10 分钟开始，
# 一直查询到常规交易时段收盘后 5 分钟。
START_AT = datetime(
    2026, 9, 11, 8, 20,
    tzinfo=EASTERN,
)

END_AT = datetime(
    2026, 9, 11, 16, 5,
    tzinfo=EASTERN,
)

# 历史研究截止时间。
AS_OF = datetime(
    2026, 9, 14, 12, 0,
    tzinfo=EASTERN,
)


def inspect_symbol(
    provider,
    symbol: str,
) -> None:
    """检查单只证券的分钟行情及正式收盘日线。"""

    print(f"\n========== {symbol} ==========")

    request = HistoricalMinuteBarsRequest(
        symbol=symbol,
        start_at=START_AT,
        end_at=END_AT,
        as_of=AS_OF,
    )

    # ---------- 1. 查询历史分钟行情 ----------

    try:
        bars = provider.get_intraday_bars(
            symbol,
            start_at=request.start_at,
            end_at=request.end_at,
            as_of=request.as_of,
        )

    except MarketDataProviderError as exc:
        print(
            "minute_error=",
            type(exc).__name__,
        )
        bars = []

    print("minute_count=", len(bars))
    # ---------- 2. 验证分钟行情质量 ----------

    if bars:
        quality = validate_intraday_bars(
            request=request,
            bars=bars,
            required_sessions=[
                "pre",
                "regular",
            ],
        )

        coverage = inspect_intraday_coverage(
            request=request,
            bars=bars,
            required_sessions={
                "pre",
                "regular",
            },
        )

        print("quality_status=", quality.status)

        print(
            "quality_issues=",
            [
                issue.code
                for issue in quality.issues
            ],
        )

        print(
            "session_counts=",
            coverage.observed_counts,
        )

        print(
            "coverage_status=",
            coverage.status,
        )

        print(
            "first_bar=",
            coverage.first_bar_at,
        )

        print(
            "last_bar_end=",
            coverage.last_bar_end_at,
        )

        # ---------- 3. 检查关键时间附近的 K 线 ----------

        # 08:30：CPI 计划发布时间
        # 09:30：美股常规交易时段开盘
        for hour, minute in (
            (8, 30),
            (9, 30),
        ):
            anchor = datetime(
                2026, 9, 11,
                hour, minute,
                tzinfo=EASTERN,
            )

            # 查找时间点前后两分钟的 K 线。
            nearby = [
                bar
                for bar in bars
                if abs(
                    (
                        bar.start_at.astimezone(EASTERN)
                        - anchor
                    ).total_seconds()
                ) <= 120
            ]

            print(
                f"\nNear {anchor:%H:%M} ET:"
            )

            if not nearby:
                print("No bars observed")

            for bar in nearby:
                print(
                    "start_at=",
                    bar.start_at.astimezone(EASTERN),
                    "session=",
                    bar.session,
                    "close=",
                    bar.close,
                    "adjustment=",
                    bar.adjustment,
                )

    # ---------- 4. 查询正式收盘日线 ----------

    close_at, session_date = resolve_close_at(
        SCHEDULED_AT
    )

    try:
        daily = get_target_daily_bar(
            provider=provider,
            symbol=symbol,
            close_at=close_at,
            as_of=AS_OF,
        )

    except MarketDataProviderError as exc:
        print(
            "daily_error=",
            type(exc).__name__,
        )
        daily = None

    print(
        "\ntarget_session=",
        session_date,
    )

    if daily is None:
        print("daily_status=unavailable")

    else:
        print("daily_status=available")
        print("daily_close=", daily.close)
        print("daily_end_at=", daily.end_at)
        print(
            "daily_adjustment=",
            daily.adjustment,
        )


def main() -> None:
    """依次检查三只证券的真实历史行情。"""

    load_dotenv(
        ROOT / "backend" / ".env",
        override=False,
    )

    provider = build_longbridge_market_provider()

    print("event=CPI August 2026")
    print("scheduled_at=", SCHEDULED_AT)
    print("as_of=", AS_OF)

    for symbol in SYMBOLS:
        inspect_symbol(
            provider=provider,
            symbol=symbol,
        )


if __name__ == "__main__":
    main()
