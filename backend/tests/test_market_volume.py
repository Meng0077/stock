from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_agent.market.schemas import Bar
from stock_agent.market.technical import build_market_technical_snapshot
from stock_agent.market.volume import (
    build_volume_features,
    calculate_average_volume,
)


def make_bar(
    day: int,
    *,
    volume: int,
    is_complete: bool = True,
) -> Bar:
    start_at = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    ) + timedelta(days=day)
    end_at = start_at + timedelta(hours=6)

    return Bar(
        symbol="TEST",
        timeframe="1d",
        start_at=start_at,
        end_at=end_at,
        updated_at=end_at,
        received_at=end_at,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=volume,
        is_complete=is_complete,
        adjustment="split_adjusted",
        source="fixture",
        data_mode="fixture",
    )


def test_volume_features_compare_latest_with_previous_20_days():
    bars = [
        make_bar(day, volume=100)
        for day in range(20)
    ] + [make_bar(20, volume=150)]

    result = build_volume_features(bars)

    assert result.latest_completed_at == bars[-1].end_at
    assert result.latest_volume == 150
    assert result.volume_adjustment == "provider_reported"
    assert result.baseline_volume_20d == Decimal("100")
    assert result.avg_volume_5d == Decimal("110")
    assert result.rvol == Decimal("1.5")
    assert result.volume_trend_ratio == Decimal("1.1")


def test_volume_features_mark_insufficient_history():
    bars = [
        make_bar(day, volume=100)
        for day in range(20)
    ]

    result = build_volume_features(bars)

    assert result.baseline_volume_20d is None
    assert result.rvol is None
    assert result.volume_trend_ratio is None
    assert result.avg_volume_5d == Decimal("100")


def test_zero_volume_baseline_has_no_ratio():
    bars = [
        make_bar(day, volume=0)
        for day in range(20)
    ] + [make_bar(20, volume=100)]

    result = build_volume_features(bars)

    assert result.baseline_volume_20d == Decimal("0")
    assert result.rvol is None
    assert result.volume_trend_ratio is None


def test_snapshot_excludes_incomplete_bar_from_volume_features():
    completed = [
        make_bar(day, volume=100)
        for day in range(20)
    ] + [make_bar(20, volume=150)]
    bars = completed + [
        make_bar(
            21,
            volume=9_999,
            is_complete=False,
        )
    ]

    snapshot = build_market_technical_snapshot(
        symbol="TEST",
        quote=None,
        bars=bars,
        is_live_query=True,
    )

    assert snapshot.volume_features.latest_volume == 150
    assert snapshot.volume_features.rvol == Decimal("1.5")


def test_average_volume_and_empty_features():
    assert calculate_average_volume(
        [100, 200, 300],
        period=2,
    ) == Decimal("250")
    assert calculate_average_volume(
        [100],
        period=2,
    ) is None

    result = build_volume_features([])
    assert result.latest_completed_at is None
    assert result.latest_volume is None
    assert result.baseline_volume_20d is None
    assert result.avg_volume_5d is None
    assert result.rvol is None
    assert result.volume_trend_ratio is None
