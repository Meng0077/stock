from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_agent.market.fixtures import FIXTURE_BARS, FIXTURE_QUOTES
from stock_agent.market.indicators import (
    calculate_atr,
    calculate_ma,
    calculate_return,
)
from stock_agent.market.price_structure import (
    PriceLevel,
    PriceSwing,
    build_price_structure_snapshot,
    calculate_fibonacci_levels,
    classify_price_levels,
    find_pivots,
)
from stock_agent.market.schemas import Bar
from stock_agent.market.technical import (
    build_market_technical_snapshot,
    calculate_current_bar_structure,
    prepare_technical_inputs,
)


def make_current_bar(
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
) -> Bar:
    """构造 Step5 测试使用的 incomplete Daily Bar。

    这里只负责提供合法测试数据。
    测试重点是 CurrentBarStructure 的计算，
    不是再次测试 Bar schema。
    """

    start_at = datetime(
        2026,
        9,
        23,
        13,
        30,
        tzinfo=timezone.utc,
    )

    end_at = start_at + timedelta(
        hours=6,
        minutes=30,
    )

    return Bar(
        symbol="NVDA",
        timeframe="1d",
        start_at=start_at,
        end_at=end_at,
        updated_at=None,
        received_at=start_at,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1_000_000,
        is_complete=False,
        adjustment="forward_adjusted",
        source="fixture",
        data_mode="fixture",
    )


def make_completed_bar(
    day: int,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    volume: int = 100,
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
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
        is_complete=True,
        adjustment="split_adjusted",
        source="fixture",
        data_mode="fixture",
    )

def test_current_bar_structure_normal_case():
    bar = make_current_bar(
        open_="100",
        high="125",
        low="100",
        close="119",
    )

    result = calculate_current_bar_structure(
        current_bar=bar,
        current_price=Decimal("120"),
        previous_close=Decimal("100"),
    )

    assert result.open == Decimal("100")
    assert result.high == Decimal("125")
    assert result.low == Decimal("100")

    # Bar.close 可以和最新 Quote 不同。
    assert result.close == Decimal("119")
    assert result.current_price == Decimal("120")

    assert (
        result.change_from_previous_close_pct
        == Decimal("20")
    )

    assert (
        result.intraday_range_pct
        == Decimal("25")
    )

    assert (
        result.range_position_pct
        == Decimal("80")
    )

    assert (
        result.pullback_from_high_pct
        == Decimal("4")
    )

    assert (
        result.rebound_from_low_pct
        == Decimal("20")
    )

def test_current_bar_structure_with_zero_range():
    bar = make_current_bar(
        open_="100",
        high="100",
        low="100",
        close="100",
    )

    result = calculate_current_bar_structure(
        current_bar=bar,
        current_price=Decimal("100"),
        previous_close=Decimal("100"),
    )

    assert (
        result.intraday_range_pct
        == Decimal("0")
    )

    assert (
        result.range_position_pct
        is None
    )

    assert (
        result.pullback_from_high_pct
        == Decimal("0")
    )

    assert (
        result.rebound_from_low_pct
        == Decimal("0")
    )


def test_quote_can_extend_current_bar_high():
    bar = make_current_bar(
        open_="100",
        high="110",
        low="100",
        close="109",
    )

    result = calculate_current_bar_structure(
        current_bar=bar,
        current_price=Decimal("120"),
        previous_close=Decimal("100"),
    )

    # 最新 Quote 已经创造新的日内高点。
    assert result.high == Decimal("120")

    assert result.low == Decimal("100")

    assert (
        result.intraday_range_pct
        == Decimal("20")
    )

    # 当前价格就是新的 high。
    assert (
        result.range_position_pct
        == Decimal("100")
    )

    assert (
        result.pullback_from_high_pct
        == Decimal("0")
    )

    assert (
        result.rebound_from_low_pct
        == Decimal("20")
    )

def test_current_bar_structure_without_previous_close():
    bar = make_current_bar(
        open_="100",
        high="125",
        low="100",
        close="120",
    )

    result = calculate_current_bar_structure(
        current_bar=bar,
        current_price=Decimal("120"),
        previous_close=None,
    )

    assert (
        result.change_from_previous_close_pct
        is None
    )

    # 其他特征仍然正常存在。
    assert (
        result.intraday_range_pct
        == Decimal("25")
    )

    assert (
        result.range_position_pct
        == Decimal("80")
    )


def test_atr_uses_full_wilder_history():
    bars = []
    base_price = Decimal("100")
    for day in range(20):
        spread = Decimal(day + 1)
        bars.append(
            make_completed_bar(
                day,
                open_=str(base_price),
                high=str(base_price + spread),
                low=str(base_price - spread),
                close=str(base_price + Decimal("1")),
            )
        )
        base_price += Decimal("1")

    assert calculate_atr(bars) == Decimal(
        "22.97469990182661986077229725"
    )


def test_ma_and_return_use_fixed_close_windows():
    closes = [Decimal(value) for value in range(1, 52)]

    assert calculate_ma(closes, period=5) == Decimal("49")
    assert calculate_ma(closes, period=20) == Decimal("41.5")
    assert calculate_ma(closes, period=50) == Decimal("26.5")
    assert calculate_return(
        [
            Decimal("100"),
            Decimal("101"),
            Decimal("102"),
            Decimal("103"),
            Decimal("104"),
            Decimal("110"),
        ],
        period=5,
    ) == Decimal("10.0")


def test_pivot_tie_uses_rightmost_equal_high_and_confirmation_time():
    highs = ["10", "12", "14", "14", "13", "12"]
    bars = [
        make_completed_bar(
            day,
            open_="8",
            high=high,
            low="6",
            close="8",
        )
        for day, high in enumerate(highs)
    ]

    pivots = find_pivots(bars)
    highs_only = [pivot for pivot in pivots if pivot.kind == "high"]

    assert len(highs_only) == 1
    assert highs_only[0].occurred_at == bars[3].end_at
    assert highs_only[0].confirmed_at == bars[5].end_at


def test_price_level_candidates_include_distances_and_limit():
    occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    levels = [
        PriceLevel(
            price=Decimal(str(price)),
            lower_bound=Decimal(str(price)),
            upper_bound=Decimal(str(price)),
            touches=2,
            first_touch_at=occurred_at,
            last_touch_at=occurred_at,
        )
        for price in [60, 70, 80, 90, 110, 120, 130, 140]
    ]

    candidates = classify_price_levels(
        levels,
        current_price=Decimal("100"),
        atr=Decimal("10"),
    )

    assert [level.price for level in candidates.support] == [
        Decimal("90"),
        Decimal("80"),
        Decimal("70"),
    ]
    assert [level.price for level in candidates.resistance] == [
        Decimal("110"),
        Decimal("120"),
        Decimal("130"),
    ]
    assert candidates.support[0].price_distance == Decimal("10")
    assert candidates.support[0].atr_distance == Decimal("1")


def test_price_structure_handles_insufficient_data():
    result = build_price_structure_snapshot(
        completed_bars=[],
        current_price=None,
        atr14=None,
    )

    assert result.support_candidates == []
    assert result.resistance_candidates == []
    assert result.current_zone is None
    assert result.fibonacci is None


def test_day21_fixture_builds_technical_snapshot():
    bars = FIXTURE_BARS[("NVDA", "1d")]
    inputs = prepare_technical_inputs(
        quote=FIXTURE_QUOTES["NVDA"],
        bars=bars,
        is_live_query=True,
    )

    assert len(inputs.completed_bars) == 2
    assert inputs.current_bar == bars[-1]

    snapshot = build_market_technical_snapshot(
        symbol="nvda",
        quote=FIXTURE_QUOTES["NVDA"],
        bars=bars,
        is_live_query=True,
    )

    assert snapshot.symbol == "NVDA"
    assert snapshot.calculation_version == "technical-v1"
    assert snapshot.current_price == Decimal("200.00")
    assert snapshot.atr14 is None
    assert snapshot.current_bar_structure is not None


def test_completed_only_snapshot_has_no_current_bar_structure():
    bars = [
        make_completed_bar(
            day,
            open_=str(100 + day),
            high=str(102 + day),
            low=str(99 + day),
            close=str(101 + day),
            volume=100 if day < 20 else 150,
        )
        for day in range(21)
    ]

    snapshot = build_market_technical_snapshot(
        symbol="test",
        quote=None,
        bars=bars,
        is_live_query=False,
    )

    assert snapshot.current_price == Decimal("121")
    assert snapshot.price_source == "completed_close"
    assert snapshot.current_bar_structure is None


def test_empty_technical_snapshot_marks_price_unavailable():
    snapshot = build_market_technical_snapshot(
        symbol="test",
        quote=None,
        bars=[],
        is_live_query=False,
    )

    assert snapshot.current_price is None
    assert snapshot.price_source is None
    assert snapshot.current_bar_structure is None


def test_down_fibonacci_uses_swing_low_as_retracement_base():
    occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = PriceSwing(
        direction="down",
        start_price=Decimal("120"),
        end_price=Decimal("100"),
        start_at=occurred_at,
        end_at=occurred_at + timedelta(days=1),
    )

    levels = calculate_fibonacci_levels(swing)

    assert levels.level_236 == Decimal("104.720")
