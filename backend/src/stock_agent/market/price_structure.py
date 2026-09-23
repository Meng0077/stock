from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from stock_agent.market.indicators import calculate_recent_high, calculate_recent_low
from stock_agent.market.schemas import Bar


class PivotPoint(BaseModel):
    """历史 K 线形成的局部价格极值。

    occurred_at:
        极值实际发生在哪根 K 线上。

    confirmed_at:
        经过右侧 window 根 K 后，
        我们什么时候才能确认它是一个 Pivot。

    confirmed_at 的存在可以避免未来做回测时产生 look-ahead bias。
    """
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    kind: Literal["high", "low"]

    price: Decimal

    occurred_at: datetime

    confirmed_at: datetime


def find_pivots(
    bars: list[Bar],
    *,
    window: int = 2,
) -> list[PivotPoint]:
    """从完成的 Daily Bars 中寻找局部 Pivot High / Low。

    算法：
        Pivot High:
            当前 high 不低于左边所有 high，
            并严格高于右边所有 high。

        Pivot Low:
            当前 low 不高于左边所有 low，
            并严格低于右边所有 low。

    不负责：
        - 支撑阻力判断；
        - ATR 聚类；
        - 趋势判断；
        - 获取行情。
    """

    required_bars = window * 2 + 1
    if len(bars) < required_bars:
        return []
    pivots: list[PivotPoint] = []
    for index in range(window, len(bars) - window):
        cur = bars[index]
        left = bars[index-window:index]
        right = bars[index+1:index+window+1]

        is_pivot_high = all(cur.high >= bar.high for bar in left) and all(cur.high > bar.high for bar in right)
        is_pivot_low = all(cur.low <=bar.low for bar in left) and all(cur.low < bar.low for bar in right)
        if is_pivot_high:
            pivots.append(PivotPoint(
                kind="high",
                price=cur.high,
                occurred_at=cur.end_at,
                confirmed_at=bars[index+window].end_at
            ))
        if is_pivot_low:
            pivots.append(PivotPoint(
                kind="low",
                price=cur.low,
                occurred_at=cur.end_at,
                confirmed_at=bars[index+window].end_at
            ))
    return pivots

class PriceLevel(BaseModel):
    """由多个接近的 Pivot 聚合形成的候选价格区域。

    price:
        该区域的代表价格。
        第一版使用簇内 Pivot 价格的平均值。

    touches:
        有多少个 Pivot 被聚合到这个区域。

    first_touch_at / last_touch_at:
        该区域最早和最近一次出现 Pivot 的时间。

    注意：
        PriceLevel 本身还不是 support / resistance。
        要结合 current_price 后才能分类。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    price: Decimal

    lower_bound: Decimal
    upper_bound: Decimal

    touches: int

    first_touch_at: datetime

    last_touch_at: datetime

    # 分类为候选价位以后，相对当前参考价的距离。
    price_distance: Decimal | None = None
    atr_distance: Decimal | None = None


def calculate_level_tolerance(
    atr: Decimal,
    *,
    ratio: Decimal = Decimal("0.25"),
) -> Decimal:
    """计算 Pivot 聚类使用的价格容差。

    Args:
        atr:
            当前 Wilder ATR。

        ratio:
            ATR 的使用比例。默认 0.25。

    Returns:
        两个 Pivot 可以被视为同一价格区域的最大近似距离。
    """

    return atr * ratio

def cluster_price_levels(
    pivots: list[PivotPoint],
    *,
    atr: Decimal,
    tolerance_ratio: Decimal = Decimal("0.25"),
) -> list[PriceLevel]:
    """把价格接近的 Pivot 聚合成 PriceLevel。

    Args:
        pivots:
            已经确认的 PivotPoint。
            可以同时包含 Pivot High 和 Pivot Low。

        atr:
            当前 Wilder ATR，用于根据股票自身波动尺度
            决定聚类容差。

        tolerance_ratio:
            聚类容差占 ATR 的比例。0.25 ATR。

    Returns:
        按价格从低到高排列的 PriceLevel。

    算法：
        1. Pivot 按价格排序；
        2. 第一个 Pivot 创建第一个 cluster；
        3. 后续 Pivot 与当前 cluster 的平均价格比较；
        4. 距离不超过 tolerance 则加入；
        5. 否则结束当前 cluster，并开始新 cluster。

    不负责：
        - 判断 support / resistance；
        - 给 PriceLevel 打强弱分；
        - 获取 ATR；
        - 获取行情。
    """
    if not pivots:
        return []
    tolerance = atr * tolerance_ratio
    sorted_pivots = sorted(pivots, key=lambda pivot: pivot.price)

    clusters: list[list[PivotPoint]] = []
    current_cluster = [sorted_pivots[0]]
    for pivot in sorted_pivots[1:]:
        ave = sum((item.price for item in current_cluster), Decimal("0")) / Decimal(len(current_cluster))
        if abs(pivot.price - ave) <= tolerance:
            current_cluster.append(pivot)
        else:
            clusters.append(current_cluster)
            current_cluster = [ pivot ]

    clusters.append(current_cluster)
    levels: list[PriceLevel] = []
    for cluster in clusters:
        pivot_prices = [pivot.price for pivot in cluster]

        ave = sum(pivot_prices, Decimal("0")) / Decimal(len(cluster))
        occurred_times = [pivot.occurred_at for pivot in cluster]
        levels.append(PriceLevel(
            price=ave,
            lower_bound=min(pivot_prices),
            upper_bound=max(pivot_prices),
            touches=len(cluster),
            first_touch_at=min(occurred_times),
            last_touch_at=max(occurred_times),
        ))
    return levels

class PriceLevelCandidates(BaseModel):
    """相对于当前价格分类后的价格结构区域。"""

    model_config = ConfigDict(
        extra="forbid"
    )

    support: list[PriceLevel]

    resistance: list[PriceLevel]

    # 当前价格正处于其中的结构区域。
    current_zone: PriceLevel | None


def classify_price_levels(
    levels: list[PriceLevel],
    *,
    current_price: Decimal,
    atr: Decimal,
    minimum_touches: int = 2,
    limit: int = 3,
) -> PriceLevelCandidates:
    """根据当前价格把历史 PriceLevel 分类。

    Args:
        levels:
            已经由 Pivot 聚类得到的历史价格区域。

        current_price:
            当前分析使用的市场价格。

        minimum_touches:
            至少包含多少个 Pivot，
            才作为普通支撑/阻力候选。
            第一版默认 2。

        limit:
            支撑和阻力最多各返回多少个。

    Returns:
        support:
            当前价格下方的候选区域，
            按距离当前价格由近到远排列。

        resistance:
            当前价格上方的候选区域，
            按距离当前价格由近到远排列。

        current_zone:
            当前价格正处于其中的历史结构区域。

    不负责：
        - 判断区域一定有效；
        - 输出强支撑/强阻力结论；
        - 预测突破或反弹。
    """
    support: list[PriceLevel] = []
    resistance: list[PriceLevel] = []
    current_zones: list[PriceLevel] = []

    for level in levels:
        if level.touches >= minimum_touches:
            price_distance = abs(level.price - current_price)
            candidate = level.model_copy(
                update={
                    "price_distance": price_distance,
                    "atr_distance": price_distance / atr,
                }
            )
            if level.upper_bound < current_price:
                support.append(candidate)

            if level.lower_bound > current_price:
                resistance.append(candidate)

            if level.lower_bound <= current_price <= level.upper_bound:
                current_zones.append(candidate)

    support.sort(key=lambda level: level.upper_bound, reverse=True)
    resistance.sort(key=lambda level: level.lower_bound)
    current_zone = None
    if current_zones:
        current_zone = min(
            current_zones,
            key=lambda level: abs(level.price - current_price)
        )

    return PriceLevelCandidates(
        support=support[:limit],
        resistance=resistance[:limit],
        current_zone=current_zone,
    )

def get_previous_swing_high(
    pivots: list[PivotPoint],
) -> PivotPoint | None:
    """返回最近一个已经确认的 Pivot High。"""

    highs = [pivot for pivot in pivots if pivot.kind == "high"]
    if not highs:
        return None

    return max(highs, key=lambda high: high.occurred_at)

def get_previous_swing_low(
    pivots: list[PivotPoint],
) -> PivotPoint | None:
    """返回最近一个已经确认的 Pivot low。"""

    lows = [pivot for pivot in pivots if pivot.kind == "low"]
    if not lows:
        return None

    return max(lows, key=lambda high: high.occurred_at)


GapDirection = Literal[
    "up",
    "down",
]

GapStatus = Literal[
    "open",
    "partial",
    "filled",
]
class PriceGap(BaseModel):
    """Daily Bars 之间形成的完整价格缺口。

    lower_bound / upper_bound:
        Gap 对应的实际价格区域。

    occurred_at:
        Gap 所在交易日开始的时间。

    confirmed_at:
        当前这根 Daily Bar 完成以后，
        才能确认它确实形成了完整 Gap。

    status:
        open:
            后续价格完全没有进入 Gap。

        partial:
            后续价格进入过 Gap，
            但没有完全穿过 Gap。

        filled:
            Gap 已经被完全回补。

    filled_at:
        Gap 完全回补的时间。
        未完全回补时为 None。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    direction: GapDirection

    lower_bound: Decimal
    upper_bound: Decimal

    occurred_at: datetime
    confirmed_at: datetime

    status: GapStatus

    filled_at: datetime | None

def detect_gaps(
    bars: list[Bar],
) -> list[PriceGap]:
    """从 completed Daily Bars 中识别完整价格缺口。

    Args:
        bars:
            按时间从旧到新排列的 completed daily bars。

    Returns:
        按 Gap 发生时间从旧到新排列的 PriceGap。

        函数同时检查后续 Bars，
        判断每个 Gap 当前是：
            open
            partial
            filled

    Gap 定义：
        Gap Up:
            current.low > previous.high

        Gap Down:
            current.high < previous.low

    注意：
        这里识别的是 full price gap，
        不是单纯的开盘跳空。

    每发现一个 Gap
        ↓
    扫描它之后的 Bar
        ↓
    有没有重新进入 Gap？
        │
        ├─ 没有 → open
        │
        ├─ 进入一部分 → partial
        │
        └─ 穿过另一侧边界 → filled
    """

    if len(bars) < 2:
        return []
    gaps: list[PriceGap] = []

    for index in range(1, len(bars)):
        pre = bars[index-1]
        cur = bars[index]

        direction = None
        lower_bound = None
        upper_bound = None

        if pre.high < cur.low:
            direction = 'up'
            lower_bound = pre.high
            upper_bound = cur.low
        elif pre.low > cur.high:
            direction = 'down'
            lower_bound = cur.high
            upper_bound = pre.low

        if not direction or not lower_bound or not upper_bound:
            continue

        status: GapStatus = "open"
        filled_at: datetime | None = None
        following_bars = bars[index+1:]

        for following in following_bars:
            if direction == 'up':
                if following.low <= lower_bound:
                    status = "filled"
                    filled_at = following.end_at
                    break
                if following.low <= upper_bound:
                    status = "partial"
            else:
                if following.high >= upper_bound:
                    status = "filled"
                    filled_at = following.end_at
                    break

                if following.high >= lower_bound:
                    status = "partial"
        gaps.append(PriceGap(
            direction=direction,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            occurred_at=cur.start_at,
            confirmed_at=cur.end_at,
            status=status,
            filled_at=filled_at,
        ))
    return gaps

class PriceSwing(BaseModel):
    """由两个已确认 Pivot 构成的一段完整价格 Swing。

    direction:
        up:
            Pivot Low -> Pivot High

        down:
            Pivot High -> Pivot Low

    start / end:
        分别记录 Swing 起点和终点。

    这里只描述已经完成的历史价格运动，
    不代表未来趋势方向。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    direction: Literal[
        "up",
        "down",
    ]

    start_price: Decimal
    end_price: Decimal

    start_at: datetime
    end_at: datetime


def select_latest_swing(
    pivots: list[PivotPoint],
) -> PriceSwing | None:
    """从已确认 Pivot 中选择最近一段完整 Swing。

    Args:
        pivots:
            已确认的 PivotPoint。
            正常情况下按 occurred_at 从旧到新排列。

    Returns:
        最近一个 Pivot 与其之前最近的 opposite Pivot
        构成的 PriceSwing。

        找不到两个相反类型 Pivot 时返回 None。

    规则：
        latest = 最近的 Pivot。

        然后从 latest 向前查找：
            如果 latest 是 high，
            找最近的 low。

            如果 latest 是 low，
            找最近的 high。

    不负责：
        - 判断 Swing 是否值得交易；
        - Fibonacci 计算；
        - 趋势预测。
    """

    if len(pivots) < 2:
        return None

    latest = max(pivots, key=lambda pivot: pivot.occurred_at)

    earlier_pivots = [
        pivot for pivot in pivots
        if (
            pivot.occurred_at < latest.occurred_at
            and pivot.kind != latest.kind
        )
    ]

    if not earlier_pivots:
        return None

    previous_opposite = max(earlier_pivots, key=lambda pivot: pivot.occurred_at)
    if previous_opposite.kind == 'low' and latest.kind == 'high':
        direction = 'up'
    else:
        direction = 'down'
    return PriceSwing(
        direction=direction,
        start_price=previous_opposite.price,
        end_price=latest.price,
        start_at=previous_opposite.occurred_at,
        end_at=latest.occurred_at,
    )

class FibonacciLevels(BaseModel):
    """最近完成 Swing 对应的 Fibonacci retracement levels."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    direction: Literal[
        "up",
        "down",
    ]

    start_price: Decimal
    end_price: Decimal

    start_at: datetime
    end_at: datetime

    level_236: Decimal
    level_382: Decimal
    level_500: Decimal
    level_618: Decimal
    level_786: Decimal

FIBONACCI_RATIOS = {
    "236": Decimal("0.236"),
    "382": Decimal("0.382"),
    "500": Decimal("0.500"),
    "618": Decimal("0.618"),
    "786": Decimal("0.786"),
}

def calculate_fibonacci_levels(
    swing: PriceSwing,
) -> FibonacciLevels:
    """根据已经完成的 PriceSwing 计算 Fibonacci 回撤位。

    Args:
        swing:
            已经通过 Pivot 确认的一段完整上涨或下跌 Swing。

    Returns:
        常用 Fibonacci retracement levels：
            23.6%
            38.2%
            50.0%
            61.8%
            78.6%

    计算规则：

        上涨 Swing:
            low -> high

            level =
                high
                - range * retracement_ratio

        下跌 Swing:
            high -> low

            level =
                low
                + range * retracement_ratio

    不负责：
        - 判断 Fib Level 是支撑还是阻力；
        - 判断价格是否会反弹；
        - 生成交易信号。
    """

    range = abs(swing.end_price - swing.start_price)

    def calculate_level(ratio: Decimal) -> Decimal:
        if swing.direction == 'up':
            return swing.end_price - range * ratio
        return swing.end_price + range * ratio

    return FibonacciLevels(
        direction=swing.direction,
        start_price=swing.start_price,
        end_price=swing.end_price,
        start_at=swing.start_at,
        end_at=swing.end_at,
        level_236=calculate_level(FIBONACCI_RATIOS["236"]),
        level_382=calculate_level(FIBONACCI_RATIOS["382"]),
        level_500=calculate_level(FIBONACCI_RATIOS["500"]),
        level_618=calculate_level(FIBONACCI_RATIOS["618"]),
        level_786=calculate_level(FIBONACCI_RATIOS["786"]),
    )

def is_meaningful_swing(
    swing: PriceSwing,
    *,
    atr: Decimal,
    minimum_atr_multiple: Decimal = Decimal("1"),
) -> bool:
    """
    判断 Swing 幅度是否足够大，值得生成 Fibonacci。
    Swing Range >= 1 ATR
    """
    swing_range = abs(swing.start_price - swing.end_price)
    return swing_range >= atr * minimum_atr_multiple


class PriceStructureSnapshot(BaseModel):
    """Daily K 产生的确定性价格结构特征。"""

    model_config = ConfigDict(
        extra="forbid"
    )

    recent_high_20d: Decimal | None
    recent_low_20d: Decimal | None

    previous_swing_high: PivotPoint | None
    previous_swing_low: PivotPoint | None

    support_candidates: list[PriceLevel]
    resistance_candidates: list[PriceLevel]

    current_zone: PriceLevel | None

    active_gaps: list[PriceGap]

    fibonacci: FibonacciLevels | None

def build_price_structure_snapshot(
    *,
    completed_bars: list[Bar],
    current_price: Decimal | None,
    atr14: Decimal | None,
) -> PriceStructureSnapshot:
    """组装 completed Daily Bars 对应的价格结构快照。

    Args:
        completed_bars:
            按时间从旧到新排列的 completed daily bars。

            调用方负责保证这些 Bar：
            - 已完成；
            - 时间有序；
            - adjustment 口径一致。

        current_price:
            当前分析使用的参考价格。

            用于把历史 PriceLevel 分类为：
            - support candidate；
            - resistance candidate；
            - current zone。

            如果当前没有可用价格，则不进行上述分类。

        atr14:
            当前 Wilder ATR14。

            用于：
            - Pivot 价格聚类；
            - 判断最新 Swing 是否足够大，
              值得生成 Fibonacci。

            ATR 不足时，仍然可以计算：
            - recent high / low；
            - Pivot；
            - previous swing；
            - Gap。

    Returns:
        PriceStructureSnapshot。

    不负责：
        - 获取行情；
        - 计算 ATR；
        - 判断 bullish / bearish；
        - 输出交易信号。
    """
    recent_high_20d = calculate_recent_high(completed_bars, period=20)
    recent_low_20d = calculate_recent_low(completed_bars, period=20)

    pivots = find_pivots(completed_bars, window=2)
    previous_swing_high = get_previous_swing_high(pivots)
    previous_swing_low = get_previous_swing_low(pivots)

    candidates = PriceLevelCandidates(
        support=[],
        resistance=[],
        current_zone=None,
    )
    if (
        atr14 is not None
        and current_price is not None
    ):
        levels = cluster_price_levels(pivots, atr=atr14, tolerance_ratio=Decimal("0.25"))
        candidates = classify_price_levels(
            levels,
            current_price=current_price,
            atr=atr14,
        )

    gaps = detect_gaps(completed_bars)

    latest_swing = select_latest_swing(pivots)
    fibonacci = None
    if (
        latest_swing is not None
        and atr14 is not None
        and is_meaningful_swing(latest_swing, atr=atr14)
    ):
        fibonacci = calculate_fibonacci_levels(latest_swing)

    return PriceStructureSnapshot(
        recent_high_20d=recent_high_20d,
        recent_low_20d=recent_low_20d,
        previous_swing_high=previous_swing_high,
        previous_swing_low=previous_swing_low,
        support_candidates=candidates.support,
        resistance_candidates=candidates.resistance,
        current_zone=candidates.current_zone,
        active_gaps=[gap for gap in gaps if gap.status != "filled"],
        fibonacci=fibonacci,
    )
