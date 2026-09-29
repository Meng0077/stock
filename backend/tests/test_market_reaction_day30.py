"""Day30 Step 3：Market Reaction 异常与时间边界验收。

全部使用 Fixture，不读取密钥，不发送真实行情请求。
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from stock_agent.macro.models.release import MacroReleaseEvent

from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.fixture_provider import (
    FixtureMarketDataProvider,
)
from stock_agent.market.intraday import (
    HistoricalMinuteBarsRequest,
    IntradayBar,
)
from stock_agent.market.schemas import (
    Bar,
    BarTimeframe,
    PriceAdjustment,
)

from stock_agent.market_reaction.comparison import (
    compare_event_symbols,
)
from stock_agent.market_reaction.multi_symbol import (
    research_multi_symbol_event_reaction,
)
from stock_agent.market_reaction.service import (
    research_event_reaction,
)
from stock_agent.market_reaction.trading_calendar import (
    resolve_close_at,
)

from stock_agent.quality.intraday import (
    validate_intraday_bars,
)


EASTERN = ZoneInfo("America/New_York")

EVENT_AT = datetime(
    2026, 9, 11, 8, 30,
    tzinfo=EASTERN,
)

AS_OF = datetime(
    2026, 9, 14, 12, 0,
    tzinfo=EASTERN,
)

WINDOWS = ("5m", "30m", "1h", "close")


# ============================================================
# 1. 构造测试数据
# ============================================================


def make_release(
    event_at: datetime = EVENT_AT,
    *,
    release_date: date | None = None,
    has_actual_time: bool = True,
) -> MacroReleaseEvent:
    """构造模拟宏观发布事件。"""

    day = release_date or event_at.astimezone(
        EASTERN
    ).date()

    return MacroReleaseEvent(
        release_id=f"cpi:{day.isoformat()}",
        release_type="cpi",
        release_date=day,
        scheduled_release_at=event_at,
        released_at=(
            event_at if has_actual_time else None
        ),
        release_date_source="fixture",
        schedule_source="fixture",
        period_binding="verified",
        metrics=[],
    )


def get_session(
    start_at: datetime,
) -> str:
    """根据纽约当地时间，标注本次 Fixture 的交易时段。"""

    local = start_at.astimezone(EASTERN)

    clock = (local.hour, local.minute)

    if clock < (9, 30):
        return "pre"

    if clock < (16, 0):
        return "regular"

    return "post"


def make_minute_bar(
    *,
    symbol: str,
    start_at: datetime,
    price: str,
) -> IntradayBar:
    """构造一根完整的原始分钟 K 线。"""

    end_at = start_at + timedelta(minutes=1)

    value = Decimal(price)

    return IntradayBar(
        symbol=symbol,
        start_at=start_at,
        end_at=end_at,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=100,
        is_complete=True,
        adjustment="raw",
        updated_at=end_at,
        received_at=end_at,
        source="fixture",
        data_mode="fixture",
        session=get_session(start_at),
    )


def make_daily_bar(
    *,
    symbol: str,
    close_at: datetime,
    price: str,
) -> Bar:
    """根据实际交易所收盘时间构造日线。

    不将所有交易日的收盘时间固定为 16:00，
    因为某些交易日可能提前收盘。
    """

    local_close = close_at.astimezone(EASTERN)

    start_at = datetime.combine(
        local_close.date(),
        time(9, 30),
        tzinfo=EASTERN,
    )

    value = Decimal(price)

    return Bar(
        symbol=symbol,
        timeframe="1d",
        start_at=start_at,
        end_at=close_at,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=1000,
        is_complete=True,
        adjustment="raw",
        updated_at=close_at,
        received_at=close_at,
        source="fixture",
        data_mode="fixture",
    )


def make_symbol_bars(
    symbol: str,
    *,
    event_at: datetime = EVENT_AT,
) -> dict[tuple[str, BarTimeframe], list[Bar]]:
    """生成一只证券的标准测试行情。

    参考价：100
    T+5m：105
    T+30m：110
    T+1h：120
    Close：130

    对应收益率：5%、10%、20%、30%。
    """

    minute_bars = [
        # 事件前最后一根完整 K 线。
        make_minute_bar(
            symbol=symbol,
            start_at=event_at - timedelta(minutes=1),
            price="100",
        ),

        # 事件发生后的第一根 K 线。
        make_minute_bar(
            symbol=symbol,
            start_at=event_at,
            price="101",
        ),

        # 08:34–08:35：T+5m。
        make_minute_bar(
            symbol=symbol,
            start_at=event_at + timedelta(minutes=4),
            price="105",
        ),

        # 08:59–09:00：T+30m。
        make_minute_bar(
            symbol=symbol,
            start_at=event_at + timedelta(minutes=29),
            price="110",
        ),

        # 09:29–09:30：T+1h。
        make_minute_bar(
            symbol=symbol,
            start_at=event_at + timedelta(minutes=59),
            price="120",
        ),
    ]

    # 由交易所日历决定事件后的第一次正式收盘。
    # 周五盘后事件将自动对应下周一。
    close_at, _ = resolve_close_at(event_at)

    daily_bar = make_daily_bar(
        symbol=symbol,
        close_at=close_at,
        price="130",
    )

    return {
        (symbol, "1m"): minute_bars,
        (symbol, "1d"): [daily_bar],
    }


def make_bars(
    *,
    symbols: tuple[str, ...] = (
        "NVDA",
        "QQQ",
        "SOXL",
    ),
    event_at: datetime = EVENT_AT,
) -> dict[tuple[str, BarTimeframe], list[Bar]]:
    """合并多只证券的测试行情。"""

    bars = {}

    for symbol in symbols:
        bars.update(
            make_symbol_bars(
                symbol,
                event_at=event_at,
            )
        )

    return bars


# ============================================================
# 2. 故障注入 Provider
# ============================================================


class FaultInjectingProvider(FixtureMarketDataProvider):
    """允许指定某只证券的分钟或日线请求失败。"""

    def __init__(
        self,
        *,
        bars: dict[
            tuple[str, BarTimeframe],
            list[Bar],
        ],
        minute_error_symbol: str | None = None,
        daily_error_symbol: str | None = None,
    ) -> None:
        super().__init__(
            quotes={},
            bars=bars,
        )

        self.minute_error_symbol = minute_error_symbol
        self.daily_error_symbol = daily_error_symbol

        self.minute_calls = 0
        self.daily_calls = 0

    def get_intraday_bars(
        self,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        as_of: datetime,
    ) -> list[IntradayBar]:
        self.minute_calls += 1

        if symbol == self.minute_error_symbol:
            raise MarketDataProviderError(
                f"{symbol}: simulated minute API failure"
            )

        return super().get_intraday_bars(
            symbol,
            start_at=start_at,
            end_at=end_at,
            as_of=as_of,
        )

    def get_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        timeframe: BarTimeframe,
        limit: int,
        include_incomplete: bool = False,
        adjustment: PriceAdjustment | None = None,
    ) -> list[Bar]:
        self.daily_calls += 1

        if symbol == self.daily_error_symbol:
            raise MarketDataProviderError(
                f"{symbol}: simulated daily API failure"
            )

        return super().get_bars(
            symbol,
            as_of=as_of,
            timeframe=timeframe,
            limit=limit,
            include_incomplete=include_incomplete,
            adjustment=adjustment,
        )


# ============================================================
# 3. 测试：缺少特定观察窗口
# ============================================================


def test_missing_5m_preserves_other_windows() -> None:
    """缺少 5m 行情，不应影响其他窗口。"""

    bars = make_bars(symbols=("NVDA",))

    # 删除 08:34–08:35 的目标分钟线。
    target_start = EVENT_AT + timedelta(minutes=4)

    bars[("NVDA", "1m")] = [
        bar
        for bar in bars[("NVDA", "1m")]
        if bar.start_at != target_start
    ]

    provider = FixtureMarketDataProvider(
        quotes={},
        bars=bars,
    )

    result = research_event_reaction(
        release=make_release(),
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    assert result.reference_price == Decimal("100")

    assert result.observations["5m"].status == "missing"

    assert result.observations["30m"].status == "usable"
    assert result.observations["1h"].status == "usable"
    assert result.observations["close"].status == "usable"

    assert result.observations["5m"].return_pct is None


# ============================================================
# 4. 测试：事件前参考价格缺失
# ============================================================


def test_missing_reference_blocks_all_returns() -> None:
    """没有参考价格，不能计算任何收益率。"""

    bars = make_bars(symbols=("NVDA",))

    reference_start = EVENT_AT - timedelta(minutes=1)

    bars[("NVDA", "1m")] = [
        bar
        for bar in bars[("NVDA", "1m")]
        if bar.start_at != reference_start
    ]

    provider = FixtureMarketDataProvider(
        quotes={},
        bars=bars,
    )

    result = research_event_reaction(
        release=make_release(),
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    assert result.reference_price is None
    assert "pre_bar_missing" in result.issues

    for window in WINDOWS:
        observation = result.observations[window]

        assert observation.status == "unavailable"
        assert observation.return_pct is None


# ============================================================
# 5. 测试：多证券 API 异常隔离
# ============================================================


def test_provider_failures_are_isolated() -> None:
    """QQQ 分钟请求失败、SOXL 日线请求失败。

    NVDA 应完全正常；
    SOXL 应保留分钟收益；
    QQQ 的异常不应中断整批研究。
    """

    provider = FaultInjectingProvider(
        bars=make_bars(),
        minute_error_symbol="QQQ",
        daily_error_symbol="SOXL",
    )

    event = research_multi_symbol_event_reaction(
        release=make_release(),
        symbols=("NVDA", "QQQ", "SOXL"),
        provider=provider,
        as_of=AS_OF,
    )

    nvda = event.reactions["NVDA"]
    qqq = event.reactions["QQQ"]
    soxl = event.reactions["SOXL"]

    # NVDA：所有窗口正常。
    assert all(
        nvda.observations[window].status == "usable"
        for window in WINDOWS
    )

    # QQQ：分钟 API 故障，不应伪造收益率。
    assert qqq.reference_price is None
    assert qqq.observations == {}

    assert (
        "minute_data_provider_error"
        in qqq.issues
    )

    # SOXL：分钟数据正常，只有日线失败。
    for window in ("5m", "30m", "1h"):
        assert soxl.observations[window].status == "usable"

    assert soxl.observations["close"].status == "unavailable"

    assert (
        "daily_data_provider_error"
        in soxl.issues
    )

    # 比较结果同样保留各窗口的可用性。
    comparison = compare_event_symbols(
        event=event,
        lhs_symbol="NVDA",
        rhs_symbol="SOXL",
    )

    assert comparison.observations["5m"].status == "usable"

    assert (
        comparison.observations["close"].status
        == "unavailable"
    )

    assert (
        comparison.observations["close"].difference_pp
        is None
    )


# ============================================================
# 6. 测试：目标日线缺失
# ============================================================


def test_missing_daily_bar_preserves_minute_results() -> None:
    """日线没有返回时，分钟结果不应丢失。"""

    bars = make_bars(symbols=("NVDA",))

    # Provider 支持查询日线，但没有目标日线。
    bars[("NVDA", "1d")] = []

    provider = FixtureMarketDataProvider(
        quotes={},
        bars=bars,
    )

    result = research_event_reaction(
        release=make_release(),
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    for window in ("5m", "30m", "1h"):
        assert result.observations[window].status == "usable"

    close = result.observations["close"]

    assert close.status == "missing"
    assert close.reason == "daily_close_unavailable"
    assert close.return_pct is None


# ============================================================
# 7. 测试：as_of 防止未来数据
# ============================================================


def test_as_of_prevents_future_observations() -> None:
    """事件发布后 10 分钟，不能提前看到 30m、1h 和收盘。"""

    cutoff = EVENT_AT + timedelta(minutes=10)

    provider = FaultInjectingProvider(
        bars=make_bars(symbols=("NVDA",)),
    )

    result = research_event_reaction(
        release=make_release(),
        symbol="NVDA",
        provider=provider,
        as_of=cutoff,
    )

    assert result.observations["5m"].status == "usable"

    assert result.observations["30m"].status == "pending"

    assert result.observations["1h"].status == "pending"

    assert result.observations["close"].status == "pending"

    assert result.observations["30m"].return_pct is None
    assert result.observations["1h"].return_pct is None
    assert result.observations["close"].return_pct is None

    # 还没收盘，不应该调用日线 API。
    assert provider.daily_calls == 0


# ============================================================
# 8. 测试：盘前到常规交易时段
# ============================================================


def test_observation_windows_cross_market_open() -> None:
    """事件在 09:15 发布，30m 和 1h 跨越 09:30。

    观察窗口必须按自然时间计算，
    不能在常规交易时段开始时重新计时。
    """

    event_at = datetime(
        2026, 9, 11, 9, 15,
        tzinfo=EASTERN,
    )

    provider = FixtureMarketDataProvider(
        quotes={},
        bars=make_bars(
            symbols=("NVDA",),
            event_at=event_at,
        ),
    )

    result = research_event_reaction(
        release=make_release(event_at),
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    assert result.observations["5m"].price_at == (
        event_at + timedelta(minutes=5)
    )

    assert result.observations["30m"].price_at == (
        event_at + timedelta(minutes=30)
    )

    assert result.observations["1h"].price_at == (
        event_at + timedelta(hours=1)
    )

    assert result.observations["30m"].return_pct == (
        Decimal("10")
    )

    assert result.observations["1h"].return_pct == (
        Decimal("20")
    )


# ============================================================
# 9. 测试：周五盘后事件
# ============================================================


def test_after_hours_event_uses_monday_close() -> None:
    """周五 17:00 发布的事件，应使用下周一正式收盘。"""

    event_at = datetime(
        2026, 9, 11, 17, 0,
        tzinfo=EASTERN,
    )

    as_of = datetime(
        2026, 9, 15, 12, 0,
        tzinfo=EASTERN,
    )

    close_at, session_date = resolve_close_at(event_at)

    assert session_date == "2026-09-14"

    assert close_at == datetime(
        2026, 9, 14, 16, 0,
        tzinfo=EASTERN,
    )

    provider = FixtureMarketDataProvider(
        quotes={},
        bars=make_bars(
            symbols=("NVDA",),
            event_at=event_at,
        ),
    )

    result = research_event_reaction(
        release=make_release(event_at),
        symbol="NVDA",
        provider=provider,
        as_of=as_of,
    )

    close = result.observations["close"]

    assert close.status == "usable"
    assert close.target_at == close_at
    assert close.price == Decimal("130")
    assert close.return_pct == Decimal("30")


# ============================================================
# 10. 测试：交易所节假日
# ============================================================


def test_holiday_uses_next_trading_session() -> None:
    """2026 年 1 月 1 日休市，下一个交易日为 1 月 2 日。

    这里只测试交易所日历，不伪造休市日的分钟行情。
    """

    event_at = datetime(
        2026, 1, 1, 8, 30,
        tzinfo=EASTERN,
    )

    close_at, session_date = resolve_close_at(event_at)

    assert session_date == "2026-01-02"

    assert close_at == datetime(
        2026, 1, 2, 16, 0,
        tzinfo=EASTERN,
    )


# ============================================================
# 11. 测试：发布时间和发布日期冲突
# ============================================================


def test_invalid_release_time_stops_before_market_request() -> None:
    """发布日期与实际发布时间冲突，应拒绝计算。"""

    provider = FaultInjectingProvider(
        bars=make_bars(symbols=("NVDA",)),
    )

    # release_date=9 月 10 日，
    # released_at=9 月 11 日。
    release = make_release(
        EVENT_AT,
        release_date=date(2026, 9, 10),
    )

    result = research_event_reaction(
        release=release,
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    assert result.event_at is None

    assert result.observations == {}

    assert (
        "release_date_time_conflict"
        in result.issues
    )

    # 时间证据不成立，不能继续请求行情。
    assert provider.minute_calls == 0
    assert provider.daily_calls == 0


# ============================================================
# 12. 测试：缺少实际发布时间
# ============================================================


def test_missing_actual_time_does_not_query_market() -> None:
    """不能使用 scheduled_release_at 冒充实际发布时间。"""

    provider = FaultInjectingProvider(
        bars=make_bars(symbols=("NVDA",)),
    )

    release = make_release(
        EVENT_AT,
        has_actual_time=False,
    )

    result = research_event_reaction(
        release=release,
        symbol="NVDA",
        provider=provider,
        as_of=AS_OF,
    )

    assert result.event_at is None
    assert result.observations == {}

    assert "actual_release_time_missing" in result.issues

    assert provider.minute_calls == 0
    assert provider.daily_calls == 0


# ============================================================
# 13. 测试：底层分钟行情数据质量
# ============================================================


def test_quality_rejects_duplicate_minute_bars() -> None:
    """相同时间的重复 K 线应被质量模块拒绝。"""

    request = HistoricalMinuteBarsRequest(
        symbol="NVDA",
        start_at=EVENT_AT - timedelta(minutes=5),
        end_at=EVENT_AT + timedelta(hours=2),
        as_of=AS_OF,
    )

    bar = make_minute_bar(
        symbol="NVDA",
        start_at=EVENT_AT - timedelta(minutes=1),
        price="100",
    )

    quality = validate_intraday_bars(
        request=request,
        bars=[bar, bar],
        required_sessions=["pre"],
    )

    assert quality.status == "rejected"

    assert any(
        issue.code == "duplicate_intraday_bar"
        for issue in quality.issues
    )


def test_quality_rejects_future_bar_update() -> None:
    """更新时间晚于 as_of 的 K 线不能通过质量检查。"""

    request = HistoricalMinuteBarsRequest(
        symbol="NVDA",
        start_at=EVENT_AT - timedelta(minutes=5),
        end_at=EVENT_AT + timedelta(hours=2),
        as_of=AS_OF,
    )

    bar = make_minute_bar(
        symbol="NVDA",
        start_at=EVENT_AT - timedelta(minutes=1),
        price="100",
    )

    bar = bar.model_copy(
        update={
            "updated_at": AS_OF + timedelta(minutes=1)
        }
    )

    quality = validate_intraday_bars(
        request=request,
        bars=[bar],
        required_sessions=["pre"],
    )

    assert quality.status == "rejected"

    assert any(
        issue.code == "intraday_update_after_as_of"
        for issue in quality.issues
    )