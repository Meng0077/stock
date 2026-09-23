from decimal import Decimal

from stock_agent.market.schemas import Bar


def calculate_ma(
    closes: list[Decimal],
    *,
    period: int,
) -> Decimal | None:
    """计算最近 period 个收盘价的简单移动平均线。

    """
    if len(closes) < period:
        return None

    return (
        sum(closes[-period:], Decimal("0"))
        / Decimal(period)
    )


def calculate_return(
    closes: list[Decimal],
    *,
    period: int,
) -> Decimal | None:
    """计算最近 period 个交易日的收盘价涨跌幅。
    """

    # 5 日收益率需要今天和 5 个交易日前，
    # 即至少 6 根收盘价。
    if len(closes) < period + 1:
        return None

    previous_close = closes[-period - 1]
    latest_close = closes[-1]


    return (
        (latest_close / previous_close - Decimal("1"))
        * Decimal("100")
    )


def calculate_true_range(
    *,
    high: Decimal,
    low: Decimal,
    previous_close: Decimal,
) -> Decimal:
    """计算单根 K 线相对于前一交易日收盘价的真实波幅。

    TR 同时考虑当日振幅以及隔夜跳空。
    """
    return max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close),
    )


def calculate_atr(
    bars: list[Bar],
    *,
    period: int = 14,
) -> Decimal | None:
    """计算 Wilder ATR。

    Args:
        bars:
            按时间从旧到新排列的 completed daily bars。

            调用方应尽量传入完整的可用历史窗口，
            而不是只传 period + 1 根，
            因为 Wilder ATR 会递归继承前面的 ATR 状态。

        period:
            ATR 周期，通常为 14。

    Returns:
        当前最新一根 Bar 对应的 ATR。

        数据不足 period + 1 根时返回 None。

    算法：
        1. 每根 Bar 与前一根 close 计算 True Range；
        2. 前 period 个 TR 的简单平均作为 seed ATR；
        3. 后续使用 Wilder smoothing 递归更新。

    不负责：
        - 获取行情；
        - Bar 排序；
        - incomplete Bar 处理。
    """
    if len(bars) < period + 1:
        return None

    true_ranges: list[Decimal] = []

    for index in range(1, len(bars)):
        previous = bars[index - 1]
        current = bars[index]

        tr = calculate_true_range(
            high=current.high,
            low=current.low,
            previous_close=previous.close,
        )

        true_ranges.append(tr)

    # 前 period 个 TR 先生成 seed ATR。
    atr = (
        sum(
            true_ranges[:period],
            Decimal("0"),
        )
        / Decimal(period)
    )

    for true_range in true_ranges[period:]:
        atr = (
            atr * Decimal(period - 1)
            + true_range
        ) / Decimal(period)

    return atr


def calculate_recent_high(
    bars: list[Bar],
    *,
    period: int,
) -> Decimal | None:
    """计算最近 period 根完成 K 线中的最高价。
    """

    if len(bars) < period:
        return None

    return max(
        bar.high
        for bar in bars[-period:]
    )


def calculate_recent_low(
    bars: list[Bar],
    *,
    period: int,
) -> Decimal | None:
    """计算最近 period 根完成 K 线中的最低价。"""

    if len(bars) < period:
        return None

    return min(
        bar.low
        for bar in bars[-period:]
    )



if __name__ == "__main__":
    closes = [
        Decimal(str(value))
        for value in [100, 102, 104, 103, 105, 108]
    ]

    assert calculate_ma(
        closes,
        period=5,
    ) == Decimal("104.4")

    assert calculate_return(
        closes,
        period=5,
    ) == Decimal("8")

    # 模拟某日跳空高开：
    # 前收盘 13，当日最低 18，最高 20。
    # 虽然当天高低价之差只有 2，
    # 但考虑跳空后的 TR 应该是 7。
    assert calculate_true_range(
        high=Decimal("20"),
        low=Decimal("18"),
        previous_close=Decimal("13"),
    ) == Decimal("7")

    print('success')
