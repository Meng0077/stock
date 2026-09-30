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


def calculate_ma_slope(
    closes: list[Decimal],
    *,
    period: int,
    lookback: int = 5,
) -> Decimal | None:
    """计算均线在过去 lookback 个交易日的百分比变化。"""
    if len(closes) < period + lookback:
        return None

    current_ma = calculate_ma(closes, period=period)
    previous_ma = calculate_ma(
        closes[:-lookback],
        period=period,
    )
    if current_ma is None or previous_ma is None:
        return None

    return (
        (current_ma / previous_ma - Decimal("1"))
        * Decimal("100")
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

def calculate_rsi(
    closes: list[Decimal],
    *,
    period: int = 14,
) -> Decimal | None:
    """
    使用 Wilder smoothing 计算 RSI。

    RSI 用最近价格上涨和下跌的平均幅度，
    描述当前价格动能的强弱。

    注意：
    - RSI 本身不直接代表 bullish / bearish；
    - RSI > 70 不代表价格一定会跌；
    - RSI < 30 也不代表价格一定会涨；
    - MomentumFactor 会把 RSI 当作动能状态辅助信息。

    数据至少需要 period + 1 个 close，
    因为 14 个价格变化需要 15 个收盘价。
    """
    if len(closes) < period + 1:
        return None

    gains: list[Decimal] = []
    losses: list[Decimal] = []

    # RSI 使用相邻两个收盘价的变化。
    #
    # 上涨：
    #   gain = change
    #   loss = 0
    #
    # 下跌：
    #   gain = 0
    #   loss = abs(change)

    for index in range(1, len(closes)):
        change = (
            closes[index]
            - closes[index - 1]
        )

        if change > 0:
            gains.append(change)
            losses.append(Decimal("0"))
        elif change < 0:
            gains.append(Decimal("0"))
            losses.append(-change)
        else:
            gains.append(Decimal("0"))
            losses.append(Decimal("0"))

    # Wilder RSI 的第一组平均涨跌幅使用简单平均。
    average_gain = (
        sum(
            gains[:period],
            Decimal("0"),
        )
        / Decimal(period)
    )

    average_loss = (
        sum(
            losses[:period],
            Decimal("0"),
        )
        / Decimal(period)
    )

    # 后续数据不再重新做普通平均，
    # 而是使用 Wilder smoothing：
    #
    # new_average =
    # (
    #     previous_average * (period - 1)
    #     + current_value
    # ) / period
    #
    # 这和 ATR 的 Wilder smoothing 思路一致。
    for gain, loss in zip(
        gains[period:],
        losses[period:],
    ):
        average_gain = (
            average_gain
            * Decimal(period - 1)
            + gain
        ) / Decimal(period)

        average_loss = (
            average_loss
            * Decimal(period - 1)
            + loss
        ) / Decimal(period)

    # 整段时间价格完全没有变化。
    #
    # 没有上涨也没有下跌，
    # 使用 RSI=50 表示中性状态。
    if (
        average_gain == 0
        and average_loss == 0
    ):
        return Decimal("50")

    # 没有任何平均下跌幅度，
    # 表示这一段动能完全偏向上涨。
    if average_loss == 0:
        return Decimal("100")

    # 没有任何平均上涨幅度，
    # 表示这一段动能完全偏向下跌。
    if average_gain == 0:
        return Decimal("0")

    relative_strength = (
        average_gain / average_loss
    )

    return (
        Decimal("100")
        - Decimal("100")
        / (
            Decimal("1")
            + relative_strength
        )
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
