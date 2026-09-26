"""根据长桥历史数据寻找最近一次可用的宏观发布。"""

from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from stock_agent.macro.release_builders import (
    resolve_vendor_time,
)
from stock_agent.macro.models.release import MacroReleaseType
from stock_agent.macro.providers.longbridge_indicators import (
    IndicatorKey,
)
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroProvider,
)


EASTERN = ZoneInfo("America/New_York")


RELEASE_ANCHORS: dict[
    MacroReleaseType,
    IndicatorKey,
] = {
    "cpi": ("cpi", "mom"),
    "ppi": ("ppi", "mom"),
    "pce": ("pce", "mom"),
    "employment_situation": (
        "nonfarm_payrolls",
        "monthly_change",
    ),
    "weekly_claims": ("initial_claims", "level"),
}

LOOKBACK_DAYS: dict[MacroReleaseType, int] = {
    "cpi": 90,
    "ppi": 90,
    "pce": 90,
    "employment_situation": 90,
    "weekly_claims": 28,
}


def find_latest_available_release_date(
    *,
    macro: LongbridgeMacroProvider,
    release_type: MacroReleaseType,
    as_of: datetime,
    vendor_timezone: tzinfo,
) -> date | None:
    """寻找 as_of 之前最近一次有 Actual 的发布。

    仅用于普通在线研究，不提供历史 PIT 保证。
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    research_date = as_of.astimezone(EASTERN).date()

    end_date = research_date - timedelta(days=1)

    start_date = end_date - timedelta(
        days=LOOKBACK_DAYS[release_type]
    )

    indicator, measure = RELEASE_ANCHORS[release_type]

    history = macro.get_history(
        indicator,
        measure,
        start_date=start_date,
        end_date=end_date,
    )

    candidates: list[date] = []

    for record in history:
        # 未来事件可能已有 Forecast，但尚无 Actual。
        if record.actual is None:
            continue

        if record.vendor_release_at is None:
            continue

        vendor_time = resolve_vendor_time(
            record.vendor_release_at,
            vendor_timezone=vendor_timezone,
        )

        release_date = vendor_time.astimezone(
            EASTERN
        ).date()

        # 再次验证时间，不能只信赖 API 的查询范围。
        if not start_date <= release_date <= end_date:
            continue

        # 统计期不应晚于本次发布日期。
        if record.period > release_date:
            continue

        candidates.append(release_date)

    return max(candidates) if candidates else None