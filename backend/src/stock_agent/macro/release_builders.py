from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Final, Literal, TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from stock_agent.macro.calculations.claims import (
    calculate_weekly_claims,
    weekly_claims_to_snapshot,
)
from stock_agent.macro.calculations.consensus import merge_consensus
from stock_agent.macro.calculations.employment import (
    calculate_average_hourly_earnings,
    calculate_nonfarm_payrolls,
    calculate_unemployment_rate,
    employment_metric_to_snapshot,
)
from stock_agent.macro.calculations.inflation import (
    InflationIndicator,
    build_inflation_metrics,
    calculate_inflation_reading,
    calculate_pce_reading,
)
from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.models.metric import (
    ConsensusObservation,
    EconomicIndicator,
    EconomicMeasure,
    MacroMetricSnapshot,
)
from stock_agent.macro.models.release import (
    MacroReleaseEvent,
    MacroReleaseType,
    ReleasePeriodBinding,
)
from stock_agent.macro.providers.bea import BEAPCEProvider
from stock_agent.macro.providers.bls import BLSProvider
from stock_agent.macro.providers.fred import FredProvider
from stock_agent.macro.providers.fred_claims import (
    CLAIMS_SERIES,
    WeeklyClaimsProvider,
)
from stock_agent.macro.providers.longbridge_indicators import LONGBRIDGE_INDICATORS, IndicatorKey
from stock_agent.macro.providers.longbridge_macro import LongbridgeMacroProvider, LongbridgeMacroRecord
from stock_agent.macro.providers.trading_economics import (
    TradingEconomicsConsensusProvider,
)
if TYPE_CHECKING:
    from stock_agent.macro.models.snapshot import MacroSnapshot


INFLATION_SERIES = {
    "cpi": (
        "CUSR0000SA0",
        "CUUR0000SA0",
    ),
    "core_cpi": (
        "CUSR0000SA0L1E",
        "CUUR0000SA0L1E",
    ),
    "ppi": (
        "WPSFD4",
        "WPUFD4",
    ),
    "core_ppi": (
        "WPSFD49104",
        "WPUFD49104",
    ),
}

EMPLOYMENT_SERIES = {
    # 全部非农就业人数，季调后，单位为千人。
    "nonfarm_payrolls": "CES0000000001",

    # 美国失业率，季调后，单位为百分比。
    "unemployment_rate": "LNS14000000",

    # 私营非农平均时薪，季调后，单位为美元/小时。
    "average_hourly_earnings": "CES0500000003",
}

BLS_INFLATION_RELEASE_CONFIG = {
    "cpi": {
        "indicators": (
            "cpi",
            "core_cpi",
        ),
    },
    "ppi": {
        "indicators": (
            "ppi",
            "core_ppi",
        ),
    },
}

# 这些 Series 只用于：
#   Series -> Economic Release -> Release Dates
#
# 不用于替代 BLS / BEA 的 actual 数据。
MACRO_RELEASE_SERIES: Final[dict[MacroReleaseType, str]] = {
    "cpi": "CPIAUCSL",
    "ppi": "PPIACO",
    "employment_situation": "PAYEMS",
    "pce": "PCEPI",
    "weekly_claims": "ICSA",
}

EASTERN = ZoneInfo("America/New_York")


def research_date(as_of: datetime) -> date:
    """将研究截止时间转换为宏观发布使用的美国东部日期。"""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(EASTERN).date()


def fetch_optional_consensus(
    *,
    consensus: TradingEconomicsConsensusProvider | None,
    release_date: date,
    release_type: str,
    warnings: list[str],
) -> list[ConsensusObservation]:
    """获取可选的一致预期，不影响官方实际数据。"""

    if consensus is None:
        warnings.append(f"{release_type}_consensus_not_configured")
        return []

    try:
        return consensus.get_consensus(
            start_date=release_date,
            end_date=release_date,
        )
    except MacroDataProviderError:
        warnings.append(f"{release_type}_consensus_unavailable")
        return []


def get_latest_release_date(
    *,
    fred: FredProvider,
    series_id: str,
    as_of: date,
) -> date | None:
    """查询截至 as_of 已经发生的最近一次官方发布日期。

    这里只得到 date，不得到具体发布时间，也不证明
    release_date 与某个 reference period 已经严格一一对应。
    """

    release = fred.get_series_release(series_id)
    release_dates = fred.get_release_dates(
        release.release_id,
        include_future=False,
    )
    candidates = [
        release_date
        for release_date in release_dates
        if release_date <= as_of
    ]
    return max(candidates) if candidates else None


def build_macro_release(
    *,
    release_type: MacroReleaseType,
    release_date: date,
    metrics: list[MacroMetricSnapshot],
    release_date_source: str,
    scheduled_release_at: datetime | None = None,
    schedule_source: str | None = None,
    released_at: datetime | None = None,
    period_binding: ReleasePeriodBinding = "latest_assumed",
) -> MacroReleaseEvent:
    """组合一次宏观发布事件。

    只负责事件级组合和基本一致性校验；不调用 API，
    不计算指标，也不自动猜 reference period 或发布时间。
    """

    if not metrics:
        raise ValueError("Macro release must contain metrics")

    # 如果 metric 自己已经存在 release_date，
    # 必须和 Event 的发布日期一致。
    for metric in metrics:
        if (
            metric.release_date is not None
            and metric.release_date != release_date
        ):
            raise ValueError(
                "Metric release date does not match "
                f"{release_type} release date"
            )

    return MacroReleaseEvent(
        release_id=f"{release_type}:{release_date.isoformat()}",
        release_type=release_type,
        release_date=release_date,
        scheduled_release_at=scheduled_release_at,
        released_at=released_at,
        release_date_source=release_date_source,
        schedule_source=schedule_source,
        period_binding=period_binding,
        metrics=metrics,
    )


def resolve_scheduled_release_at(
    *,
    metrics: list[MacroMetricSnapshot],
    forecasts: list[ConsensusObservation],
) -> datetime | None:
    """尝试确定一次 Release 的计划发布时间。

    只有所有相关 Forecast 指向同一个时间时，
    才把计划时间提升到 Event 层。
    """

    metric_keys = {
        (metric.indicator, metric.measure, metric.period)
        for metric in metrics
    }
    times = {
        forecast.scheduled_release_at
        for forecast in forecasts
        if (
            forecast.indicator,
            forecast.measure,
            forecast.period,
        )
        in metric_keys
    }
    return next(iter(times)) if len(times) == 1 else None


def build_bls_inflation_release(
    *,
    bls: BLSProvider,
    consensus: TradingEconomicsConsensusProvider | None,
    fred: FredProvider,
    release_type: Literal["cpi", "ppi"],
    as_of: datetime,
    warnings: list[str],
) -> MacroReleaseEvent | None:
    """构建最新 CPI 或 PPI 发布事件。

    这是 latest research 路径。BLS actual 是当前 API
    返回的当前版本，因此 actual_pit_status 保持 unverified。
    FRED 只负责提供官方 release_date。
    """

    release_date = get_latest_release_date(
        fred=fred,
        series_id=MACRO_RELEASE_SERIES[release_type],
        as_of=research_date(as_of),
    )
    if release_date is None:
        return None
    if release_date == research_date(as_of):
        warnings.append(f"{release_type}_release_time_unverified")
        return None

    forecasts = fetch_optional_consensus(
        consensus=consensus,
        release_date=release_date,
        warnings=warnings,
        release_type=release_type,
    )
    metrics = []

    for indicator in BLS_INFLATION_RELEASE_CONFIG[release_type]["indicators"]:
        sa_series, nsa_series = INFLATION_SERIES[indicator]
        series = bls.fetch_series([sa_series, nsa_series])
        reading = calculate_inflation_reading(
            sa_points=series.get(sa_series, []),
            nsa_points=series.get(nsa_series, []),
        )
        if reading is None:
            continue

        indicator_metrics = build_inflation_metrics(
            indicator=cast(InflationIndicator, indicator),
            reading=reading,
            forecasts=forecasts,
            release_date=release_date,
            released_at=None,
        )
        metrics.extend(indicator_metrics.values())

    if not metrics:
        return None

    scheduled_release_at = resolve_scheduled_release_at(
        metrics=metrics,
        forecasts=forecasts,
    )
    return build_macro_release(
        release_type=release_type,
        release_date=release_date,
        metrics=metrics,
        release_date_source="fred",
        scheduled_release_at=scheduled_release_at,
        schedule_source=(
            "trading_economics"
            if scheduled_release_at is not None
            else None
        ),
        released_at=None,
        # FRED release/date + 最新 BLS observation
        # 目前没有严格证明 period 对应关系。
        period_binding="latest_assumed",
    )


def build_pce_release(
    *,
    bea: BEAPCEProvider,
    consensus: TradingEconomicsConsensusProvider | None,
    fred: FredProvider,
    as_of: datetime,
    warnings: list[str],
) -> MacroReleaseEvent | None:
    """构建最近一次 PCE / Core PCE 发布事件。"""

    release_date = get_latest_release_date(
        fred=fred,
        series_id=MACRO_RELEASE_SERIES["pce"],
        as_of=research_date(as_of),
    )
    if release_date is None:
        return None
    if release_date == research_date(as_of):
        warnings.append("pce_release_time_unverified")
        return None

    current_year = research_date(as_of).year
    data = bea.fetch_indexes(
        years=[current_year - 2, current_year - 1, current_year]
    )
    forecasts = fetch_optional_consensus(
        consensus=consensus,
        release_date=release_date,
        warnings=warnings,
        release_type="pce",
    )
    metrics = []

    for indicator in ("pce", "core_pce"):
        reading = calculate_pce_reading(data[indicator])
        if reading is None:
            continue

        calculated = build_inflation_metrics(
            indicator=indicator,
            reading=reading,
            forecasts=forecasts,
            release_date=release_date,
            released_at=None,
            source="bea",
        )
        metrics.extend(calculated.values())

    if not metrics:
        return None

    scheduled_release_at = resolve_scheduled_release_at(
        metrics=metrics,
        forecasts=forecasts,
    )
    return build_macro_release(
        release_type="pce",
        release_date=release_date,
        metrics=metrics,
        release_date_source="fred",
        scheduled_release_at=scheduled_release_at,
        schedule_source=(
            "trading_economics"
            if scheduled_release_at is not None
            else None
        ),
        released_at=None,
        period_binding="latest_assumed",
    )


def build_employment_release(
    *,
    bls: BLSProvider,
    fred: FredProvider,
    as_of: datetime,
    consensus: TradingEconomicsConsensusProvider | None,
    warnings: list[str],
) -> MacroReleaseEvent | None:
    """构建最近一次 Employment Situation 发布事件。

    包含：
        - Nonfarm Payrolls
        - Unemployment Rate
        - Average Hourly Earnings
    """

    release_date = get_latest_release_date(
        fred=fred,
        series_id=MACRO_RELEASE_SERIES["employment_situation"],
        as_of=research_date(as_of),
    )
    if release_date is None:
        return None
    if release_date == research_date(as_of):
        warnings.append("employment_situation_release_time_unverified")
        return None

    data = bls.fetch_series(list(EMPLOYMENT_SERIES.values()))
    metrics = []

    payrolls = calculate_nonfarm_payrolls(
        data.get(EMPLOYMENT_SERIES["nonfarm_payrolls"], [])
    )
    if payrolls is not None:
        metrics.append(
            employment_metric_to_snapshot(
                payrolls,
                release_date=release_date,
            )
        )

    unemployment = calculate_unemployment_rate(
        data.get(EMPLOYMENT_SERIES["unemployment_rate"], [])
    )
    if unemployment is not None:
        metrics.append(
            employment_metric_to_snapshot(
                unemployment,
                release_date=release_date,
            )
        )

    earnings = calculate_average_hourly_earnings(
        data.get(EMPLOYMENT_SERIES["average_hourly_earnings"], [])
    )
    metrics.extend(
        employment_metric_to_snapshot(
            metric,
            release_date=release_date,
        )
        for metric in earnings
    )

    if not metrics:
        return None

    # 检查本次就业发布的统计月份是否一致。
    periods = {metric.period for metric in metrics}
    if len(periods) != 1:
        warnings.append("employment_period_mismatch")
        return None

    forecasts = fetch_optional_consensus(
        consensus=consensus,
        release_date=release_date,
        warnings=warnings,
        release_type="employment_situation",
    )

    metrics = merge_consensus(
        metrics=metrics,
        forecasts=forecasts,
    )

    scheduled_at = resolve_scheduled_release_at(
        metrics=metrics,
        forecasts=forecasts,
    )

    return build_macro_release(
        release_type="employment_situation",
        release_date=release_date,
        metrics=metrics,
        release_date_source="fred",
        released_at=None,
        period_binding="latest_assumed",
        scheduled_release_at=scheduled_at,
        schedule_source=(
            "trading_economics" if scheduled_at is not None else None
        ),
    )


def build_weekly_claims_release(
    *,
    claims: WeeklyClaimsProvider,
    fred: FredProvider,
    consensus: TradingEconomicsConsensusProvider | None,
    as_of: datetime,
    warnings: list[str],
) -> MacroReleaseEvent | None:
    """构建最近一次周度失业金申领发布事件。

    允许三个指标拥有不同的统计周。
    不将 FRED 日期自动解释为准确的实际发布时间。
    """

    us_date = research_date(as_of)

    release_date = get_latest_release_date(
        fred=fred,
        series_id=MACRO_RELEASE_SERIES["weekly_claims"],
        as_of=us_date,
    )

    if release_date is None:
        return None
    # 目前没有经核实的实际发布时刻。发布当天保守跳过，避免提前读取实际值。
    if release_date == us_date:
        warnings.append("weekly_claims_release_time_unverified")
        return None

    metrics = []

    for indicator, series_id in CLAIMS_SERIES.items():
        points = claims.fetch_series(
            series_id,
            start_date=release_date - timedelta(days=70),
            as_of=us_date,
        )

        reading = calculate_weekly_claims(
            indicator=indicator,
            points=points,
        )

        if reading is None:
            continue

        metrics.append(
            weekly_claims_to_snapshot(
                reading,
                release_date=release_date,
            )
        )
    if not metrics:
        return None

    forecasts = fetch_optional_consensus(
        consensus=consensus,
        release_date=release_date,
        warnings=warnings,
        release_type="weekly_claims",
    )

    metrics = merge_consensus(
        metrics=metrics,
        forecasts=forecasts,
    )

    scheduled_at = resolve_scheduled_release_at(
        metrics=metrics,
        forecasts=forecasts,
    )

    return build_macro_release(
        release_type="weekly_claims",
        release_date=release_date,
        metrics=metrics,
        release_date_source="fred",
        scheduled_release_at=scheduled_at,
        schedule_source=(
            "trading_economics"
            if scheduled_at is not None
            else None
        ),
        released_at=None,
        period_binding="latest_assumed",
    )

def get_latest_release(
    snapshot: "MacroSnapshot",
    release_type: MacroReleaseType,
) -> MacroReleaseEvent | None:
    """寻找指定类型最近一次宏观发布。"""

    matches = [
        release
        for release in snapshot.recent_releases
        if release.release_type == release_type
    ]
    return max(matches, key=lambda release: release.release_date, default=None)

InflationReleaseType = Literal["cpi", "ppi", "pce"]


INFLATION_RELEASE_KEYS: dict[
    InflationReleaseType,
    tuple[IndicatorKey, ...],
] = {
    "cpi": (
        ("cpi", "mom"),
        ("cpi", "yoy"),
        ("core_cpi", "mom"),
        ("core_cpi", "yoy"),
    ),
    "ppi": (
        ("ppi", "mom"),
        ("ppi", "yoy"),
        ("core_ppi", "mom"),
        ("core_ppi", "yoy"),
    ),
    "pce": (
        ("pce", "mom"),
        ("pce", "yoy"),
        ("core_pce", "mom"),
        ("core_pce", "yoy"),
    ),
}

LaborReleaseType = Literal[
    "employment_situation",
    "weekly_claims",
]


LABOR_RELEASE_KEYS: dict[
    LaborReleaseType,
    tuple[IndicatorKey, ...],
] = {
    "employment_situation": (
        ("nonfarm_payrolls", "monthly_change"),
        ("unemployment_rate", "level"),
        ("average_hourly_earnings", "mom"),
    ),

    "weekly_claims": (
        ("initial_claims", "level"),
        ("continuing_claims", "level"),
        ("initial_claims_4w_avg", "level"),
    ),
}

def validate_labor_periods(
    release_type: LaborReleaseType,
    records: dict[
        IndicatorKey,
        LongbridgeMacroRecord,
    ],
) -> bool:
    """验证就业及失业金发布中的统计期关系。"""

    if not records:
        return False

    if release_type == "employment_situation":
        # 非农、失业率、平均时薪必须属于同一个月。
        periods = {
            record.period
            for record in records.values()
        }

        return len(periods) == 1

    # ---------- Weekly Claims ----------

    initial = records.get(
        ("initial_claims", "level")
    )

    continued = records.get(
        ("continuing_claims", "level")
    )

    average = records.get(
        ("initial_claims_4w_avg", "level")
    )

    # 四周均值应与本次 Initial Claims
    # 对应同一个统计周。
    if (
        initial is not None
        and average is not None
        and initial.period != average.period
    ):
        return False

    # 若 Initial Claims 缺失，
    # 可以使用四周均值作为统计周参考。
    reference = initial or average

    # Continuing Claims 通常滞后一周。
    # 本项目目前采用你已验证的美国周报口径。
    if (
        reference is not None
        and continued is not None
        and (reference.period - continued.period).days != 7
    ):
        return False

    # 只有部分指标可用时，仍允许构建部分发布。
    return True


def resolve_vendor_time(
    value: datetime,
    *,
    vendor_timezone: tzinfo,
) -> datetime:
    """把供应商事件时间转换为 UTC。

    SDK 返回无时区 datetime 时，必须由调用者显式
    指定其所属时区，而不是使用服务器本地时区。
    """

    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=vendor_timezone)

    if value.utcoffset() is None:
        raise ValueError("Invalid vendor timezone")

    return value.astimezone(timezone.utc)


def build_longbridge_release(
    *,
    macro: LongbridgeMacroProvider,
    release_type: InflationReleaseType,
    release_date: date,
    as_of: datetime,
    vendor_timezone: tzinfo,
    warnings: list[str],
) -> MacroReleaseEvent | None:
    """将长桥通胀记录组装为一次发布事件。

    当前支持 CPI、PPI、PCE。

    使用供应商历史数据，适用于普通在线研究；
    不提供严格历史 PIT 保证。
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    research_date = as_of.astimezone(EASTERN).date()

    # 只有供应商事件时间，没有独立核实的实际发布时间。
    # 发布当天保守跳过，避免提前使用事后回填的 Actual。
    if release_date >= research_date:
        warnings.append("cpi_release_time_unverified")
        return None


    keys = INFLATION_RELEASE_KEYS[release_type]
    records: dict[
        IndicatorKey,
        tuple[LongbridgeMacroRecord, datetime],
    ] = {}

    for indicator, measure in keys:
        key: IndicatorKey = (indicator, measure)
        label = f"{indicator}:{measure}"
        try:
            history = macro.get_history(
                indicator,
                measure,
                start_date=release_date,
                end_date=release_date,
            )
        except MacroDataProviderError:
            warnings.append(f"{release_type}_provider_unavailable:{label}")
            continue

        # 一项指标在指定发布日期应该对应唯一一条记录。
        # 不能在多条记录中随意选择最新统计期。
        if len(history) != 1:
            warnings.append(f"{release_type}_record_count_invalid:{label}")
            continue

        record = history[0]

        if (
            record.indicator != indicator
            or record.measure != measure
            or record.unit != "percent"
        ):
            warnings.append(
                f"{release_type}_record_identity_mismatch:{label}"
            )
            return None

        if record.vendor_release_at is None:
            warnings.append(f"{release_type}_release_time_missing:{label}")
            continue

        vendor_time = resolve_vendor_time(
            record.vendor_release_at,
            vendor_timezone=vendor_timezone,
        )

        # 只接受属于指定美国东部发布日期的记录。
        if (
            vendor_time.astimezone(EASTERN).date()
            != release_date
        ):
            warnings.append(
                f"{release_type}_release_date_mismatch:{label}"
            )
            return None

        records[key] = (record, vendor_time)

    if not records:
        warnings.append(
            f"{release_type}_no_usable_records"
        )
        return None

    # 第二阶段：验证所有已获取记录属于同一次发布。
    periods = {
        record.period
        for record, _ in records.values()
    }

    if len(periods) != 1:
        warnings.append(
            f"{release_type}_period_mismatch"
        )
        return None

    times = {
        vendor_time
        for _, vendor_time in records.values()
    }

    if len(times) != 1:
        warnings.append(
            f"{release_type}_release_time_mismatch"
        )
        return None

    scheduled_at = next(iter(times))

    # 第三阶段：生成有 Actual 的指标。
    metrics: list[MacroMetricSnapshot] = []

    for indicator, measure in keys:
        key: IndicatorKey = (indicator, measure)

        if key not in records:
            continue

        record, _ = records[key]

        if record.actual is None:
            warnings.append(
                f"{release_type}_actual_missing:"
                f"{indicator}:{measure}"
            )
            continue

        metrics.append(
            MacroMetricSnapshot(
                indicator=indicator,
                measure=measure,
                unit=record.unit,
                period=record.period,
                actual=record.actual,
                previous=record.previous,
                consensus=record.forecast,

                # 尚未证明 Forecast 是公布前的历史版本。
                surprise=None,
                forecast_as_of=None,
                consensus_pit_verified=False,

                release_date=release_date,

                # 供应商事件时间不能冒充官方实际发布时间。
                released_at=None,

                source="longbridge",
                actual_pit_status="unverified",
                surprise_is_estimated=False,
            )
        )
    if not metrics:
        warnings.append(
            f"{release_type}_no_usable_metrics"
        )
        return None

    if len(metrics) < len(keys):
        warnings.append(
            f"{release_type}_partial_release:"
            f"{len(metrics)}/{len(keys)}"
        )


    return MacroReleaseEvent(
        release_id=f"{release_type}:{release_date.isoformat()}",
        release_type=release_type,
        release_date=release_date,
        scheduled_release_at=scheduled_at,
        released_at=None,
        release_date_source="longbridge",
        # 已检查供应商内部的一致性，但尚未独立核实
        # 统计期与发布日期的官方绑定关系。
        period_binding="latest_assumed",

        metrics=metrics,
    )


def build_longbridge_labor_release(
    *,
    macro: LongbridgeMacroProvider,
    release_type: LaborReleaseType,
    release_date: date,
    as_of: datetime,
    vendor_timezone: tzinfo,
    warnings: list[str],
) -> MacroReleaseEvent | None:
    """组装 Employment 或 Weekly Claims 发布事件。"""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    research_date = as_of.astimezone(EASTERN).date()

    # 没有独立核实的实际发布时间时，
    # 发布当天不使用可能被事后回填的 Actual。
    if release_date >= research_date:
        warnings.append(
            f"{release_type}_release_time_unverified"
        )
        return None

    keys = LABOR_RELEASE_KEYS[release_type]

    records: dict[
        IndicatorKey,
        LongbridgeMacroRecord,
    ] = {}

    event_times: set[datetime] = set()

    # ---------- 第一阶段：查询并验证记录 ----------

    for indicator, measure in keys:
        key: IndicatorKey = (indicator, measure)
        label = f"{indicator}:{measure}"

        try:
            history = macro.get_history(
                indicator,
                measure,
                start_date=release_date,
                end_date=release_date,
            )
        except MacroDataProviderError:
            warnings.append(
                f"{release_type}_provider_unavailable:{label}"
            )
            continue

        if len(history) != 1:
            warnings.append(
                f"{release_type}_record_count_invalid:{label}"
            )
            continue

        record = history[0]
        spec = LONGBRIDGE_INDICATORS[key]

        # 校验指标身份及标准化单位。
        if (
            record.indicator != indicator
            or record.measure != measure
            or record.unit != spec.unit
        ):
            warnings.append(
                f"{release_type}_identity_mismatch:{label}"
            )
            return None

        if record.vendor_release_at is None:
            warnings.append(
                f"{release_type}_release_time_missing:{label}"
            )
            continue

        vendor_time = resolve_vendor_time(
            record.vendor_release_at,
            vendor_timezone=vendor_timezone,
        )

        # 必须属于本次指定的美国东部发布日期。
        if (
            vendor_time.astimezone(EASTERN).date()
            != release_date
        ):
            warnings.append(
                f"{release_type}_release_date_mismatch:{label}"
            )
            return None

        records[key] = record
        event_times.add(vendor_time)

    if not records:
        warnings.append(
            f"{release_type}_no_usable_records"
        )
        return None

    # ---------- 第二阶段：发布一致性校验 ----------

    if len(event_times) != 1:
        warnings.append(
            f"{release_type}_release_time_mismatch"
        )
        return None

    if not validate_labor_periods(
        release_type,
        records,
    ):
        warnings.append(
            f"{release_type}_period_mismatch"
        )
        return None

    scheduled_at = next(iter(event_times))

    # ---------- 第三阶段：组装实际指标 ----------

    metrics: list[MacroMetricSnapshot] = []

    for indicator, measure in keys:
        key: IndicatorKey = (indicator, measure)

        record = records.get(key)

        if record is None:
            continue

        if record.actual is None:
            warnings.append(
                f"{release_type}_actual_missing:"
                f"{indicator}:{measure}"
            )
            continue

        metrics.append(
            MacroMetricSnapshot(
                indicator=indicator,
                measure=measure,
                unit=record.unit,
                period=record.period,

                # get_history() 已完成单位标准化。
                actual=record.actual,
                previous=record.previous,
                consensus=record.forecast,

                # 不把未经 PIT 验证的历史预期
                # 用于严格 Surprise 计算。
                surprise=None,
                forecast_as_of=None,
                consensus_pit_verified=False,

                release_date=release_date,
                released_at=None,

                source="longbridge",
                actual_pit_status="unverified",
                surprise_is_estimated=False,
            )
        )

    if not metrics:
        warnings.append(
            f"{release_type}_no_usable_metrics"
        )
        return None

    if len(metrics) != len(keys):
        warnings.append(
            f"{release_type}_partial_release:"
            f"{len(metrics)}/{len(keys)}"
        )

    return MacroReleaseEvent(
        release_id=(
            f"{release_type}:{release_date.isoformat()}"
        ),
        release_type=release_type,
        release_date=release_date,

        scheduled_release_at=scheduled_at,
        schedule_source="longbridge",

        # 没有单独核实的实际发布时间。
        released_at=None,
        release_date_source="longbridge",

        # 供应商内部校验不等于官方 PIT 验证。
        period_binding="latest_assumed",

        metrics=metrics,
    )
