"""长桥宏观数据公布前的 Forecast 快照采集。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
import json
import os

from zoneinfo import ZoneInfo

from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.longbridge_latest import RELEASE_ANCHORS
from stock_agent.macro.release_builders import (
    INFLATION_RELEASE_KEYS,
    LABOR_RELEASE_KEYS,
    resolve_vendor_time,
)
from stock_agent.macro.models.metric import (
    EconomicIndicator,
    EconomicMeasure,
    EconomicUnit,
)
from stock_agent.macro.models.release import MacroReleaseType
from stock_agent.macro.providers.longbridge_indicators import (
    IndicatorKey,
    LONGBRIDGE_INDICATORS,
)
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroProvider,
    LongbridgeMacroRecord,
)


EASTERN = ZoneInfo("America/New_York")

RELEASE_KEYS = {
    **INFLATION_RELEASE_KEYS,
    **LABOR_RELEASE_KEYS,
}

@dataclass(frozen=True)
class ForecastQuote:
    indicator: EconomicIndicator
    measure: EconomicMeasure
    unit: EconomicUnit
    period: date
    consensus: Decimal

@dataclass(frozen=True)
class ForecastSnapshot:
    release_type: MacroReleaseType
    release_date: date
    scheduled_release_at: datetime

    # 实际完成采集的时间，而不是用户传入的历史 as_of。
    captured_at: datetime

    forecasts: tuple[ForecastQuote, ...]
    source: str = "longbridge"

def _expected_period(
    release_type: MacroReleaseType,
    key: IndicatorKey,
    anchor_period: date,
) -> date:
    """确定同一次发布中，各指标预期的统计期。"""

    if (
        release_type == "weekly_claims"
        and key == ("continuing_claims", "level")
    ):
        return anchor_period - timedelta(days=7)

    return anchor_period

def capture_next_forecasts(
    *,
    macro: LongbridgeMacroProvider,
    release_type: MacroReleaseType,
    vendor_timezone: tzinfo,
    warnings: list[str],
    lookahead_days: int = 45,
    clock: Callable[[], datetime] | None = None,
) -> ForecastSnapshot | None:
    """采集下一次尚未公布的宏观事件的当前 Forecast。

    clock 仅用于离线测试；生产环境使用真实 UTC 时间。
    """

    if lookahead_days < 1:
        raise ValueError("lookahead_days must be positive")

    get_time = clock or (
        lambda: datetime.now(timezone.utc)
    )

    started_at = get_time()

    if (
        started_at.tzinfo is None
        or started_at.utcoffset() is None
    ):
        raise ValueError("clock must return aware datetime")

    research_date = started_at.astimezone(EASTERN).date()

    anchor_key = RELEASE_ANCHORS[release_type]

    # 查询从今天到未来指定天数内的发布。
    history = macro.get_history(
        *anchor_key,
        start_date=research_date,
        end_date=(
            research_date + timedelta(days=lookahead_days)
        ),
    )

    candidates = []

    for record in history:
        if record.actual is not None:
            continue

        if record.vendor_release_at is None:
            continue

        planned_at = resolve_vendor_time(
            record.vendor_release_at,
            vendor_timezone=vendor_timezone,
        )

        if planned_at <= started_at + timedelta(minutes=1):
            continue

        release_date = planned_at.astimezone(EASTERN).date()

        if not (
            research_date
            <= release_date
            <= research_date + timedelta(days=lookahead_days)
        ):
            continue

        candidates.append((planned_at, record))

    if not candidates:
        warnings.append(
            f"{release_type}_upcoming_release_not_found"
        )
        return None

    # 选择计划发布时间最近的一次，而不是统计期最大的记录。
    scheduled_at, anchor = min(
        candidates,
        key=lambda item: item[0],
    )

    release_date = scheduled_at.astimezone(EASTERN).date()

    records: dict[IndicatorKey, LongbridgeMacroRecord] = {
        anchor_key: anchor,
    }

    # 复用已经取得的 anchor，避免重复请求。
    for key in RELEASE_KEYS[release_type]:
        if key == anchor_key:
            continue

        indicator, measure = key

        try:
            items = macro.get_history(
                indicator,
                measure,
                start_date=release_date,
                end_date=release_date,
            )
        except MacroDataProviderError:
            warnings.append(
                f"{release_type}_forecast_unavailable:"
                f"{indicator}:{measure}"
            )
            continue

        if len(items) != 1:
            warnings.append(
                f"{release_type}_forecast_record_missing:"
                f"{indicator}:{measure}"
            )
            continue

        records[key] = items[0]

    forecasts = []

    for key, record in records.items():
        spec = LONGBRIDGE_INDICATORS[key]

        if (
            record.indicator != spec.indicator
            or record.measure != spec.measure
            or record.unit != spec.unit
        ):
            warnings.append(
                f"{release_type}_forecast_identity_mismatch"
            )
            return None

        # 任何指标已经公布 Actual，都不要把这次采集
        # 冒充为完整的发布前快照。
        if record.actual is not None:
            warnings.append(
                f"{release_type}_actual_already_available"
            )
            return None

        if record.vendor_release_at is None:
            warnings.append(
                f"{release_type}_forecast_time_missing"
            )
            return None

        record_time = resolve_vendor_time(
            record.vendor_release_at,
            vendor_timezone=vendor_timezone,
        )

        if record_time != scheduled_at:
            warnings.append(
                f"{release_type}_forecast_time_mismatch"
            )
            return None

        if record.period != _expected_period(
            release_type,
            key,
            anchor.period,
        ):
            warnings.append(
                f"{release_type}_forecast_period_mismatch"
            )
            return None

        if record.forecast is None:
            # 四周平均初请人数目前没有 Forecast，
            # 不将其视为供应商故障。
            if key != ("initial_claims_4w_avg", "level"):
                warnings.append(
                    f"{release_type}_forecast_missing:"
                    f"{spec.indicator}:{spec.measure}"
                )
            continue

        forecasts.append(
            ForecastQuote(
                indicator=spec.indicator,
                measure=spec.measure,
                unit=spec.unit,
                period=record.period,
                consensus=record.forecast,
            )
        )

    # 关键：所有网络请求结束后，才记录采集完成时间。
    captured_at = get_time()

    if (
        captured_at.tzinfo is None
        or captured_at.utcoffset() is None
    ):
        raise ValueError("clock must return aware datetime")

    # 临近发布时间时停止采集。
    if captured_at >= scheduled_at - timedelta(minutes=1):
        warnings.append(
            f"{release_type}_capture_window_closed"
        )
        return None

    if not forecasts:
        warnings.append(
            f"{release_type}_no_forecasts_available"
        )
        return None

    return ForecastSnapshot(
        release_type=release_type,
        release_date=release_date,
        scheduled_release_at=scheduled_at,
        captured_at=captured_at.astimezone(timezone.utc),
        forecasts=tuple(forecasts),
    )



def append_forecast_snapshot(
    snapshot: ForecastSnapshot,
    path: Path,
) -> None:
    """追加保存快照，不覆盖之前采集的版本。

    当前适用于单进程本地采集。
    后续部署多实例时应改为数据库事务。
    """

    payload = {
        "release_type": snapshot.release_type,
        "release_date": snapshot.release_date.isoformat(),
        "scheduled_release_at": (
            snapshot.scheduled_release_at.isoformat()
        ),
        "captured_at": snapshot.captured_at.isoformat(),
        "source": snapshot.source,
        "forecasts": [
            {
                "indicator": item.indicator,
                "measure": item.measure,
                "unit": item.unit,
                "period": item.period.isoformat(),
                "consensus": str(item.consensus),
            }
            for item in snapshot.forecasts
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(
            json.dumps(payload, ensure_ascii=False) + "\n"
        )
        file.flush()
        os.fsync(file.fileno())
