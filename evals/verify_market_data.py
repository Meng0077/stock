"""Day21 Market Data 的离线验收脚本。

验证内容：
    1. Provider 支持动态 symbol；
    2. symbol 可以做基础标准化；
    3. unknown symbol 返回 None；
    4. as_of 不允许看到未来报价；
    5. 默认不返回正在形成的 Bar；
    6. include_incomplete=True 时可以看到当前 Bar；
    7. 当前 Bar 的 updated_at 必须 <= as_of；
    8. limit 能正确限制返回数量。

本脚本只使用本地 Fixture，
不会访问真实行情 API。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from stock_agent.market.fixture_provider import (
    FixtureMarketDataProvider,
)
from stock_agent.market.fixtures import (
    FIXTURE_BARS,
    FIXTURE_QUOTES,
)


NEW_YORK = ZoneInfo(
    "America/New_York"
)

def build_fixture_provider() -> FixtureMarketDataProvider:
    """创建 Day21 离线验收使用的 Fixture Provider。

    Returns:
        注入固定报价和 K 线后的 FixtureMarketDataProvider。
    """

    return FixtureMarketDataProvider(
        quotes=FIXTURE_QUOTES,
        bars=FIXTURE_BARS,
    )


def verify_quote_queries(
    provider: FixtureMarketDataProvider,
) -> None:
    """验证 Quote 查询的基本契约。

    Args:
        provider:
            待验收的 Fixture Provider。

    验证：
        - NVDA / AMD 可以通过同一接口查询；
        - symbol 大小写和首尾空格可以标准化；
        - 不存在的 symbol 返回 None；
        - as_of 早于报价时间时不能提前看到报价。
    """

    as_of = datetime(2026,9,22,12,0,tzinfo=NEW_YORK,)

    nvda = provider.get_quote(" NVDA ", as_of=as_of)
    assert nvda is not None
    assert nvda.symbol == "NVDA"

    amd = provider.get_quote("amd", as_of=as_of)
    assert amd is not None
    assert amd.symbol == "AMD"

    unknown = provider.get_quote(
        "UNKNOWN",
        as_of=as_of,
    )
    assert unknown is None

    before_quote = datetime( 2026, 9, 20, 12, 0, tzinfo=NEW_YORK,)

    future_quote = provider.get_quote(
        "NVDA",
        as_of=before_quote,
    )

    assert future_quote is None



def verify_completed_bars(
    provider: FixtureMarketDataProvider,
) -> None:
    """验证默认情况下只返回已经完成的 Bar。"""


    as_of = datetime (2026, 9, 21, 14, 0, tzinfo=NEW_YORK,)

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
    )

    # 默认 include_incomplete=False，
    # 因此 9/21 正在形成中的 Bar 不应该出现。
    assert bars

    assert all(
        bar.is_complete
        for bar in bars
    )

    assert all(
        bar.updated_at <= as_of
        for bar in bars
    )


def verify_incomplete_bar(
    provider: FixtureMarketDataProvider,
) -> None:
    """验证调用方可以显式取得当前正在形成的 Bar。"""

    as_of = datetime(2026, 9, 21, 15, 0, tzinfo=NEW_YORK,)

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
        include_incomplete=True,
    )

    assert bars

    current_bar = bars[-1]

    assert current_bar.is_complete is False

    assert (
        current_bar.updated_at
        <= as_of
    )

    assert (
        current_bar.start_at
        <= as_of
        < current_bar.end_at
    )


def verify_incomplete_bar_not_visible_too_early(
    provider: FixtureMarketDataProvider,
) -> None:
    """验证 incomplete Bar 在自身 updated_at 之前不可见。

    这验证的是 point-in-time 语义：

    即使 Fixture 数据中已经保存了 14:30 的 Bar 快照，
    13:00 的历史请求也不能提前读取这份快照。
    """

    as_of = datetime(2026, 9, 21, 13, 0, tzinfo=NEW_YORK,)

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=60,
        include_incomplete=True,
    )

    assert all(
        bar.updated_at <= as_of
        for bar in bars
    )

    assert not any(
        (
            bar.start_at.date()
            == as_of.date()
            and not bar.is_complete
        )
        for bar in bars
    )


def verify_limit(
    provider: FixtureMarketDataProvider,
) -> None:
    """验证 limit 只保留最新的指定数量 Bar。"""

    as_of = datetime(2026, 9, 22, 12, 0, tzinfo=NEW_YORK,)

    bars = provider.get_bars(
        "NVDA",
        as_of=as_of,
        timeframe="1d",
        limit=1,
        include_incomplete=True,
    )

    assert len(bars) == 1


def main() -> None:
    """运行全部 Day21 Market Data 离线验收。"""

    provider = build_fixture_provider()

    verify_quote_queries(provider)
    verify_completed_bars(provider)
    verify_incomplete_bar(provider)
    verify_incomplete_bar_not_visible_too_early(
        provider
    )
    verify_limit(provider)

    print("Day21 market data verification passed.")


if __name__ == "__main__":
    main()
