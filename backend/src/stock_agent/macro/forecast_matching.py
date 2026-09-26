
"""匹配已保存的 Forecast 和公布后的宏观数据。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json

from stock_agent.macro.forecast_capture import (
    ForecastQuote,
    ForecastSnapshot,
    RELEASE_KEYS,
)
from stock_agent.macro.models.metric import (
    EconomicIndicator,
    EconomicMeasure,
)
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.temporal import (
    EASTERN,
    validate_release_as_of,
)


CAPTURE_MARGIN = timedelta(minutes=1)


@dataclass(frozen=True)
class SurpriseComparison:
    indicator: EconomicIndicator
    measure: EconomicMeasure
    period: date

    actual: Decimal
    consensus: Decimal

    # 两个数值的数学差值，不代表已通过 PIT 验证。
    estimated_surprise: Decimal

    forecast_as_of: datetime
    forecast_source: str

    # Forecast 是否已证明早于经核实的实际发布时间。
    forecast_pre_release_verified: bool

    # Forecast、Actual 和发布事件均满足严格历史要求。
    full_pit_verified: bool



def require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Forecast timestamps must be timezone-aware"
        )


def load_forecast_snapshots(
    path: Path,
) -> list[ForecastSnapshot]:
    """读取本地已保存的 Forecast 快照。

    文件不存在时返回空列表；
    已存在但内容损坏时明确报错，不静默跳过。
    """

    if not path.exists():
        return []

    snapshots: list[ForecastSnapshot] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                payload = json.loads(line)

                release_type = payload["release_type"]

                if release_type not in RELEASE_KEYS:
                    raise ValueError(
                        "Unknown release type"
                    )

                release_date = date.fromisoformat(
                    payload["release_date"]
                )

                scheduled_at = datetime.fromisoformat(
                    payload["scheduled_release_at"]
                )

                captured_at = datetime.fromisoformat(
                    payload["captured_at"]
                )

                require_aware(scheduled_at)
                require_aware(captured_at)

                if (
                    scheduled_at.astimezone(EASTERN).date()
                    != release_date
                ):
                    raise ValueError(
                        "Release date and schedule disagree"
                    )

                # 和 Step 9 的采集安全窗口保持一致。
                if (
                    captured_at
                    >= scheduled_at - CAPTURE_MARGIN
                ):
                    raise ValueError(
                        "Snapshot captured too late"
                    )

                if payload["source"] != "longbridge":
                    raise ValueError(
                        "Unexpected forecast source"
                    )

                quotes = []
                seen = set()

                for item in payload["forecasts"]:
                    key = (
                        item["indicator"],
                        item["measure"],
                    )

                    if key not in RELEASE_KEYS[release_type]:
                        raise ValueError(
                            f"Unexpected indicator: {key}"
                        )

                    if key in seen:
                        raise ValueError(
                            f"Duplicate forecast: {key}"
                        )

                    seen.add(key)

                    consensus = Decimal(
                        item["consensus"]
                    )

                    if not consensus.is_finite():
                        raise ValueError(
                            "Invalid consensus value"
                        )

                    quotes.append(
                        ForecastQuote(
                            indicator=item["indicator"],
                            measure=item["measure"],
                            unit=item["unit"],
                            period=date.fromisoformat(
                                item["period"]
                            ),
                            consensus=consensus,
                        )
                    )

                if not quotes:
                    raise ValueError(
                        "Empty forecast snapshot"
                    )

                snapshots.append(
                    ForecastSnapshot(
                        release_type=release_type,
                        release_date=release_date,
                        scheduled_release_at=scheduled_at,
                        captured_at=captured_at,
                        forecasts=tuple(quotes),
                        source=payload["source"],
                    )
                )

            except (
                KeyError,
                TypeError,
                ValueError,
                InvalidOperation,
            ) as exc:
                raise ValueError(
                    f"Invalid forecast snapshot "
                    f"at line {line_number}"
                ) from exc

    return snapshots



def match_release_forecasts(
    *,
    release: MacroReleaseEvent,
    snapshots: list[ForecastSnapshot],
    as_of: datetime,
) -> tuple[
    MacroReleaseEvent,
    list[SurpriseComparison],
    list[str],
]:
    """匹配一次发布和已保存的 Forecast 快照。"""

    require_aware(as_of)

    warnings: list[str] = []

    validation = validate_release_as_of(
        release,
        as_of=as_of,
        strict_pit=False,
    )

    if validation.decision == "reject":
        return (
            release,
            [],
            [f"release_not_available:{validation.reason}"],
        )

    actual_release_at = release.released_at

    event_snapshots = [
        snapshot
        for snapshot in snapshots
        if (
            snapshot.release_type == release.release_type
            and snapshot.release_date == release.release_date
            and snapshot.source == "longbridge"
        )
    ]

    if not event_snapshots:
        return release, [], []

    comparisons: list[SurpriseComparison] = []
    updated_metrics = []

    for metric in release.metrics:
        candidates = []

        for snapshot in event_snapshots:
            require_aware(snapshot.captured_at)
            require_aware(
                snapshot.scheduled_release_at
            )

            # 不能使用研究截止时间之后采集的 Forecast。
            if snapshot.captured_at > as_of:
                continue

            # 采集时间必须早于当时记录的计划发布时间。
            if (
                snapshot.captured_at
                >= snapshot.scheduled_release_at
                - CAPTURE_MARGIN
            ):
                continue

            # 如果已经获得经核实的实际发布时间，
            # 还必须证明快照早于真正公布时刻。
            if (
                actual_release_at is not None
                and snapshot.captured_at >= actual_release_at
            ):
                continue

            for quote in snapshot.forecasts:
                if (
                    quote.indicator == metric.indicator
                    and quote.measure == metric.measure
                    and quote.period == metric.period
                    and quote.unit == metric.unit
                ):
                    candidates.append(
                        (snapshot, quote)
                    )

        if not candidates:
            updated_metrics.append(metric)
            warnings.append(
                f"forecast_not_found:"
                f"{metric.indicator}:{metric.measure}"
            )
            continue

        # 同一项指标选择公布前最后一次有效采集。
        latest_time = max(
            item[0].captured_at
            for item in candidates
        )

        latest = [
            item
            for item in candidates
            if item[0].captured_at == latest_time
        ]

        # 同一时刻存在不同 Forecast 时不能任意选择。
        values = {
            quote.consensus
            for _, quote in latest
        }

        if len(values) != 1:
            updated_metrics.append(metric)
            warnings.append(
                f"forecast_conflict:"
                f"{metric.indicator}:{metric.measure}"
            )
            continue

        snapshot, quote = latest[0]

        estimated_surprise = (
            metric.actual - quote.consensus
        )

        forecast_verified = (
            actual_release_at is not None
            and snapshot.captured_at < actual_release_at
        )

        full_pit_verified = (
            forecast_verified
            and metric.actual_pit_status == "verified"
            and release.period_binding == "verified"
        )

        comparisons.append(
            SurpriseComparison(
                indicator=metric.indicator,
                measure=metric.measure,
                period=metric.period,
                actual=metric.actual,
                consensus=quote.consensus,
                estimated_surprise=estimated_surprise,
                forecast_as_of=snapshot.captured_at,
                forecast_source=snapshot.source,
                forecast_pre_release_verified=(
                    forecast_verified
                ),
                full_pit_verified=full_pit_verified,
            )
        )

        updated_metrics.append(
            metric.model_copy(
                update={
                    "consensus": quote.consensus,
                    "consensus_source": snapshot.source,
                    "forecast_as_of": snapshot.captured_at,
                    "consensus_pit_verified": forecast_verified,

                    # 只有 Forecast、Actual 和发布期绑定
                    # 都通过历史验证时，才写入 surprise。
                    "surprise": (
                        estimated_surprise
                        if full_pit_verified
                        else None
                    ),

                    # 其余情况仅提供明确标注的估算差值。
                    "estimated_surprise": (
                        None
                        if full_pit_verified
                        else estimated_surprise
                    ),

                    # 该字段沿用项目原有含义：
                    # surprise 是否基于非原始发布版本计算。
                    # 本次不再用它表达 estimated_surprise。
                    "surprise_is_estimated": False,
                }
            )
        )

    return (
        release.model_copy(
            update={"metrics": updated_metrics}
        ),
        comparisons,
        warnings,
    )
