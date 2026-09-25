from datetime import date, datetime
from typing import Final, Literal, TYPE_CHECKING, cast

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
from stock_agent.macro.models.metric import (
    ConsensusObservation,
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
    consensus: TradingEconomicsConsensusProvider,
    fred: FredProvider,
    release_type: Literal["cpi", "ppi"],
    as_of: datetime,
) -> MacroReleaseEvent | None:
    """构建最新 CPI 或 PPI 发布事件。

    这是 latest research 路径。BLS actual 是当前 API
    返回的当前版本，因此 actual_pit_status 保持 unverified。
    FRED 只负责提供官方 release_date。
    """

    release_date = get_latest_release_date(
        fred=fred,
        series_id=MACRO_RELEASE_SERIES[release_type],
        as_of=as_of.date(),
    )
    if release_date is None:
        return None

    forecasts = consensus.get_consensus(
        start_date=release_date,
        end_date=release_date,
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
    consensus: TradingEconomicsConsensusProvider,
    fred: FredProvider,
    as_of: datetime,
) -> MacroReleaseEvent | None:
    """构建最近一次 PCE / Core PCE 发布事件。"""

    release_date = get_latest_release_date(
        fred=fred,
        series_id=MACRO_RELEASE_SERIES["pce"],
        as_of=as_of.date(),
    )
    if release_date is None:
        return None

    current_year = as_of.year
    data = bea.fetch_indexes(
        years=[current_year - 2, current_year - 1, current_year]
    )
    forecasts = consensus.get_consensus(
        start_date=release_date,
        end_date=release_date,
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
        as_of=as_of.date(),
    )
    if release_date is None:
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

    return build_macro_release(
        release_type="employment_situation",
        release_date=release_date,
        metrics=metrics,
        release_date_source="fred",
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
