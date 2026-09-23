"""验证 Longbridge 真实 Quote 查询。

这个脚本会真实访问 Longbridge OpenAPI，
不属于离线测试。
"""

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from stock_agent.market.longbridge_provider import (
    build_longbridge_market_provider,
)


def verify_longbridge_quote() -> None:
    """验证 NVDA 能返回统一 Quote。"""

    provider = (
        build_longbridge_market_provider()
    )

    # 给 live quote 留一点网络请求窗口。
    #
    # 当前 smoke test 的目标不是做历史 PIT，
    # 而是验证真实行情链路。
    as_of = (
        datetime.now(timezone.utc)
        + timedelta(seconds=5)
    )

    quote = provider.get_quote(
        "NVDA",
        as_of=as_of,
    )

    assert quote is not None

    assert quote.symbol == "NVDA"
    assert quote.source == "longbridge"
    assert quote.data_mode == "live"

    print(quote)


if __name__ == "__main__":
    verify_longbridge_quote()