from decimal import Decimal

from stock_agent.decision.models import (
    FactorEvidence,
    FactorOpinion,
    MarketContext,
)

TREND_VERSION = "trend-v1"

MOMENTUM_VERSION = "momentum-v1"

LEVEL_VERSION = "level-v1"

TREND_SLOPE_THRESHOLD_PCT = Decimal("0")
MOMENTUM_DIRECTION_THRESHOLD_PCT = Decimal("0")
RSI_OVERBOUGHT_THRESHOLD = Decimal("70")
RSI_MIDPOINT = Decimal("50")
RSI_OVERSOLD_THRESHOLD = Decimal("30")
LEVEL_NEAR_THRESHOLD_ATR = Decimal("0.5")


def evaluate_trend(
    context: MarketContext,
) -> FactorOpinion:
    """
    根据 Technical Snapshot 判断当前中期趋势结构。

    核心思路：
    1. MA20 / MA50 的排列描述趋势结构；
    2. MA20 / MA50 的 5 日 slope 描述均线本身是否仍在同方向移动；
    3. MA200 只描述长期位置，不参与中期 bullish / bearish 的核心判定。
    """

    technical = context.technical

    if technical is None:
        return FactorOpinion(
            factor="trend",
            status="insufficient_data",
            reasons=["technical_missing"],
            rule_version=TREND_VERSION,
        )

    # TrendFactor 真正参与核心方向判断的 5 个输入。
    #
    # current_price:
    #   当前价格相对于均线的位置。
    #
    # ma20 / ma50:
    #   判断中期均线排列。
    #
    # slope:
    #   防止只因为价格短暂冲上均线，
    #   就把仍然向下的均线结构判断成完整上涨趋势。
    price = technical.current_price
    ma20 = technical.ma20
    ma50 = technical.ma50
    ma20_slope = technical.ma20_slope_5d_pct
    ma50_slope = technical.ma50_slope_5d_pct

    # 这些字段属于 TrendFactor 的必要输入。
    #
    # MA200 不在这里，因为：
    # 即使只有 50~100 个交易日历史数据，
    # 仍然可以正常分析中期趋势。
    if (
        price is None
        or ma20 is None
        or ma50 is None
        or ma20_slope is None
        or ma50_slope is None
    ):
        return FactorOpinion(
            factor="trend",
            status="insufficient_data",
            reasons=["trend_inputs_missing"],
            rule_version=TREND_VERSION,
        )

    evidence = [
        FactorEvidence(
            metric="current_price",
            value=price,
            source="technical.current_price",
        ),
        FactorEvidence(
            metric="current_price_source",
            value=technical.price_source,
            source="technical.price_source",
        ),
        FactorEvidence(
            metric="ma20",
            value=ma20,
            source="technical.ma20",
        ),
        FactorEvidence(
            metric="ma50",
            value=ma50,
            source="technical.ma50",
        ),
        FactorEvidence(
            metric="ma20_slope_5d_pct",
            value=ma20_slope,
            source="technical.ma20_slope_5d_pct",
        ),
        FactorEvidence(
            metric="ma50_slope_5d_pct",
            value=ma50_slope,
            source="technical.ma50_slope_5d_pct",
        ),
        FactorEvidence(
            metric="slope_direction_threshold_pct",
            value=TREND_SLOPE_THRESHOLD_PCT,
            source="rule.trend-v1",
        ),
    ]

    # MA200 是长期趋势参考。
    #
    # 它不是 TrendFactor 的必要输入，
    # 有数据时记录下来，没有时不影响中期趋势判断。
    if technical.ma200 is not None:
        evidence.append(
            FactorEvidence(
                metric="ma200",
                value=technical.ma200,
                source="technical.ma200",
            ),
        )

    # 完整的上涨趋势要求：
    #
    # 价格 > MA20 > MA50
    # 且两条均线自身也都在上升。
    #
    # 这样可以避免：
    #   价格只是短期反弹到均线上方，
    #   但 MA50 实际仍然向下，
    # 却被直接判断为 bullish。
    if (
        price > ma20 > ma50
        and ma20_slope > TREND_SLOPE_THRESHOLD_PCT
        and ma50_slope > TREND_SLOPE_THRESHOLD_PCT
    ):
        signal = "bullish"
        reasons = [
            "price_above_ma20_above_ma50",
            "ma20_slope_positive",
            "ma50_slope_positive",
        ]
    # 完整的下降趋势与 bullish 对称：
    #
    # 价格 < MA20 < MA50
    # 且 MA20 / MA50 都仍在下降。
    elif (
        price < ma20 < ma50
        and ma20_slope < TREND_SLOPE_THRESHOLD_PCT
        and ma50_slope < TREND_SLOPE_THRESHOLD_PCT
    ):
        signal = "bearish"

        reasons = [
            "price_below_ma20_below_ma50",
            "ma20_slope_negative",
            "ma50_slope_negative",
        ]
    # 其他情况不强行判断方向。
    #
    # 例如：
    # - price > MA20 > MA50，但 MA50 slope < 0
    # - price > MA20，但 MA20 < MA50
    # - 两条均线 slope 一正一负
    #
    # 这些更像趋势转换或结构不一致，
    # 第一版统一记为 mixed。
    else:
        signal = "mixed"
        reasons = [
            "trend_structure_not_aligned",
        ]

    # MA200 只补充长期位置，不修改上面的 signal。
    #
    # 例如：
    # 中期可能已经 bullish，
    # 但价格仍然低于 MA200，
    # 说明长期趋势位置还没有完全转强。
    if technical.ma200 is not None:
        if price > technical.ma200:
            reasons.append("price_above_ma200")
        elif price < technical.ma200:
            reasons.append("price_below_ma200")
        else:
            reasons.append("price_at_ma200")

    return FactorOpinion(
        factor="trend",
        status="usable",
        signal=signal,
        reasons=reasons,
        evidence=evidence,
        rule_version=TREND_VERSION,
    )


def evaluate_momentum(
    context: MarketContext,
) -> FactorOpinion:
    """
    根据 ROC5、ROC20 和 RSI14 判断价格动能。

    规则：
    - ROC5 / ROC20 决定方向；
    - RSI14 描述动能强弱或极端状态；
    - RSI 不单独反转 ROC 给出的方向。

    例如：
        ROC5 > 0
        ROC20 > 0
        RSI14 = 78

    仍然属于 bullish momentum，
    只是同时处于较高 RSI 状态。
    """

    technical = context.technical
    if technical is None:
        return FactorOpinion(
            factor="momentum",
            status="insufficient_data",
            reasons=["technical_missing"],
            rule_version=MOMENTUM_VERSION,
        )

    return_5d = technical.return_5d_pct
    return_20d = technical.return_20d_pct
    rsi14 = technical.rsi14

    if return_5d is None or return_20d is None or rsi14 is None:
        return FactorOpinion(
            factor="momentum",
            status="insufficient_data",
            reasons=["momentum_inputs_missing"],
            rule_version=MOMENTUM_VERSION,
        )

    evidence = [
        FactorEvidence(
            metric="return_5d_pct",
            value=return_5d,
            source="technical.return_5d_pct",
        ),
        FactorEvidence(
            metric="return_20d_pct",
            value=return_20d,
            source="technical.return_20d_pct",
        ),
        FactorEvidence(
            metric="rsi14",
            value=rsi14,
            source="technical.rsi14",
        ),
        FactorEvidence(
            metric="return_direction_threshold_pct",
            value=MOMENTUM_DIRECTION_THRESHOLD_PCT,
            source="rule.momentum-v1",
        ),
        FactorEvidence(
            metric="rsi_overbought_threshold",
            value=RSI_OVERBOUGHT_THRESHOLD,
            source="rule.momentum-v1",
        ),
        FactorEvidence(
            metric="rsi_midpoint",
            value=RSI_MIDPOINT,
            source="rule.momentum-v1",
        ),
        FactorEvidence(
            metric="rsi_oversold_threshold",
            value=RSI_OVERSOLD_THRESHOLD,
            source="rule.momentum-v1",
        ),
    ]

    # ROC5 和 ROC20 同时为正：
    # 短期和中期价格变化方向一致向上。
    if (
        return_5d > MOMENTUM_DIRECTION_THRESHOLD_PCT
        and return_20d > MOMENTUM_DIRECTION_THRESHOLD_PCT
    ):
        signal = "bullish"

        reasons = [
            "return_5d_positive",
            "return_20d_positive",
        ]
    # 两个周期同时为负：
    # 短期和中期动能一致向下。
    elif (
        return_5d < MOMENTUM_DIRECTION_THRESHOLD_PCT
        and return_20d < MOMENTUM_DIRECTION_THRESHOLD_PCT
    ):
        signal = "bearish"

        reasons = [
            "return_5d_negative",
            "return_20d_negative",
        ]
    # 两个周期都恰好没有价格变化时，
    # 才定义成明确 neutral。
    elif (
        return_5d == MOMENTUM_DIRECTION_THRESHOLD_PCT
        and return_20d == MOMENTUM_DIRECTION_THRESHOLD_PCT
    ):
        signal = "neutral"

        reasons = [
            "returns_flat",
        ]
    # 一正一负，或者一个为 0、另一个有方向，
    # 都说明短期和中期动能不一致。
    else:
        signal = "mixed"

        reasons = [
            "momentum_horizons_not_aligned",
        ]

    # RSI 只补充当前动能状态。
    #
    # 它不会把：
    # bullish + RSI 75
    #
    # 直接改成 bearish。
    if rsi14 > RSI_OVERBOUGHT_THRESHOLD:
        reasons.append("rsi_overbought")
    elif rsi14 > RSI_MIDPOINT:
        reasons.append("rsi_positive")
    elif rsi14 == RSI_MIDPOINT:
        reasons.append("rsi_neutral")
    elif rsi14 > RSI_OVERSOLD_THRESHOLD:
        reasons.append("rsi_weak")
    else:
        reasons.append("rsi_oversold")

    return FactorOpinion(
        factor="momentum",
        status="usable",
        signal=signal,
        evidence=evidence,
        reasons=reasons,
        rule_version=MOMENTUM_VERSION,
    )


"""
1. price > recent_high_20d
   → bullish
   → breakout

2. price < recent_low_20d
   → bearish
   → breakdown

3. price 当前位于 Pivot 聚类 zone 内
   → mixed

4. support 和 resistance 都在 0.5 ATR 内
   → mixed

5. 只有 support 在 0.5 ATR 内
   → neutral
   → near_support

6. 只有 resistance 在 0.5 ATR 内
   → neutral
   → near_resistance

7. 有足够 level 数据，但都不靠近
   → neutral

8. 连可用 level 都没有
   → insufficient_data
"""

def evaluate_level(
    context: MarketContext,
) -> FactorOpinion:
    """
    判断当前价格相对于关键价格结构所处的位置。

    LevelFactor 使用：
    - 20 日最高 / 最低价；
    - Pivot 聚类形成的 support / resistance；
    - ATR 标准化距离。

    核心原则：
    - breakout / breakdown 可以形成明确方向信号；
    - 靠近 support / resistance 只是位置状态，
      不直接预测价格一定上涨或下跌；
    - 不重新计算 Pivot、ATR 或价格结构，
      直接使用 Technical Snapshot 已经准备好的结果。
    """

    technical = context.technical
    # 没有 Technical，自然无法分析价格位置。
    if technical is None:
        return FactorOpinion(
            factor="level",
            status="insufficient_data",
            reasons=["technical_missing"],
            rule_version=LEVEL_VERSION,
        )

    price = technical.current_price
    structure = technical.price_structure

    # LevelFactor 至少需要当前参考价格。
    if price is None:
        return FactorOpinion(
            factor="level",
            status="insufficient_data",
            reasons=["current_price_missing"],
            rule_version=LEVEL_VERSION,
        )

    recent_high = structure.recent_high_20d
    recent_low = structure.recent_low_20d

    # support / resistance 已经按照离当前价格
    # 从近到远排序，所以第一个就是最近的候选位。
    nearest_support = (
        structure.support_candidates[0]
        if structure.support_candidates
        else None
    )

    nearest_resistance = (
        structure.resistance_candidates[0]
        if structure.resistance_candidates
        else None
    )

    # 如果连近期高低点、Pivot zone、
    # support / resistance 都没有，
    # 就没有任何真正可以判断位置的依据。
    has_level_data = (
        recent_high is not None
        or recent_low is not None
        or structure.current_zone is not None
        or nearest_support is not None
        or nearest_resistance is not None
    )

    if not has_level_data:
        return FactorOpinion(
            factor="level",
            status="insufficient_data",
            reasons=["level_data_missing"],
            rule_version=LEVEL_VERSION,
        )

    evidence = [
        FactorEvidence(
            metric="current_price",
            value=price,
            source="technical.current_price",
        ),
        FactorEvidence(
            metric="current_price_source",
            value=technical.price_source,
            source="technical.price_source",
        ),
    ]

    # 有 20 日高点时保存下来，
    # 后面既可以判断 breakout，
    # 也方便最终解释当前价格和近期高点的关系。
    if recent_high is not None:
        evidence.append(
            FactorEvidence(
                metric="recent_high_20d",
                value=recent_high,
                source=(
                    "technical.price_structure."
                    "recent_high_20d"
                ),
            )
        )

    if recent_low is not None:
        evidence.append(
            FactorEvidence(
                metric="recent_low_20d",
                value=recent_low,
                source=(
                    "technical.price_structure."
                    "recent_low_20d"
                ),
            )
        )

    # --------------------------------------------------------
    # 1. 先判断真正的结构突破
    # --------------------------------------------------------

    if recent_high is not None and price > recent_high:
        return FactorOpinion(
            factor="level",
            status="usable",
            signal="bullish",
            evidence=evidence,
            reasons=[
                "breakout_above_20d_high",
            ],
            rule_version=LEVEL_VERSION,
        )

    if recent_low is not None and price < recent_low:
        return FactorOpinion(
            factor="level",
            status="usable",
            signal="bearish",
            evidence=evidence,
            reasons=[
                "breakdown_below_20d_low",
            ],
            rule_version=LEVEL_VERSION,
        )

    # --------------------------------------------------------
    # 2. 当前正处于历史 Pivot 聚类区域
    # --------------------------------------------------------
    if structure.current_zone is not None:
        zone = structure.current_zone
        evidence.extend([
            FactorEvidence(
                metric="current_zone_lower_bound",
                value=zone.lower_bound,
                source=(
                    "technical.price_structure."
                    "current_zone.lower_bound"
                ),
            ),
            FactorEvidence(
                metric="current_zone_upper_bound",
                value=zone.upper_bound,
                source=(
                    "technical.price_structure."
                    "current_zone.upper_bound"
                ),
            ),
        ])

        # 当前位于关键历史区域，
        # 但仅凭这个事实不能判断最终向上还是向下。
        return FactorOpinion(
            factor="level",
            status="usable",
            signal="mixed",
            evidence=evidence,
            reasons=[
                "at_key_price_zone",
            ],
            rule_version=LEVEL_VERSION,
        )
    # --------------------------------------------------------
    # 3. 判断离最近 support / resistance 是否足够近
    # --------------------------------------------------------
    near_support = (
        nearest_support is not None
        and nearest_support.atr_distance is not None
        and nearest_support.atr_distance <= LEVEL_NEAR_THRESHOLD_ATR
    )

    near_resistance = (
        nearest_resistance is not None
        and nearest_resistance.atr_distance is not None
        and nearest_resistance.atr_distance <= LEVEL_NEAR_THRESHOLD_ATR
    )

    evidence.append(
        FactorEvidence(
            metric="near_level_atr_threshold",
            value=LEVEL_NEAR_THRESHOLD_ATR,
            source="rule.level-v1",
        )
    )

    # 保存最近 support 的实际价格和 ATR 距离。
    if nearest_support is not None:
        evidence.append(
            FactorEvidence(
                metric="nearest_support",
                value=nearest_support.price,
                source=(
                    "technical.price_structure."
                    "support_candidates[0].price"
                ),
            )
        )
        evidence.append(
            FactorEvidence(
                metric="nearest_support_atr_distance",
                value=nearest_support.atr_distance,
                source=(
                    "technical.price_structure."
                    "support_candidates[0].atr_distance"
                ),
            )
        )

    if nearest_resistance is not None:
        evidence.append(
            FactorEvidence(
                metric="nearest_resistance",
                value=nearest_resistance.price,
                source=(
                    "technical.price_structure."
                    "resistance_candidates[0].price"
                ),
            )
        )

        evidence.append(
            FactorEvidence(
                metric="nearest_resistance_atr_distance",
                value=nearest_resistance.atr_distance,
                source=(
                    "technical.price_structure."
                    "resistance_candidates[0].atr_distance"
                ),
            )
        )

    # --------------------------------------------------------
    # 4. 上下关键价位都很近
    # --------------------------------------------------------
    if near_support and near_resistance:
        # 当前价格被夹在较窄的结构区间中，
        # 上下两个方向都有明显位置约束。
        return FactorOpinion(
            factor="level",
            status="usable",
            signal="mixed",
            evidence=evidence,
            reasons=[
                "near_support",
                "near_resistance",
                "inside_tight_range",
            ],
            rule_version=LEVEL_VERSION,
        )

    # --------------------------------------------------------
    # 5. 只靠近 support
    # --------------------------------------------------------
    if near_support:
        # 靠近支撑不是 bullish confirmation。
        #
        # 支撑可能守住，也可能被跌破，
        # 所以这里只描述位置，不直接给上涨方向。
        return FactorOpinion(
            factor="level",
            status="usable",
            signal="neutral",
            evidence=evidence,
            reasons=[
                "near_support",
            ],
            rule_version=LEVEL_VERSION,
        )

    # --------------------------------------------------------
    # 6. 只靠近 resistance
    # --------------------------------------------------------

    if near_resistance:
        # 同理，靠近阻力本身也不是 bearish confirmation。
        #
        # 价格既可能受阻回落，也可能直接突破。
        return FactorOpinion(
            factor="level",
            status="usable",
            signal="neutral",
            evidence=evidence,
            reasons=[
                "near_resistance",
            ],
            rule_version=LEVEL_VERSION,
        )

    # --------------------------------------------------------
    # 7. 有结构数据，但当前不在明显关键位置
    # --------------------------------------------------------

    return FactorOpinion(
        factor="level",
        status="usable",
        signal="neutral",
        evidence=evidence,
        reasons=[
            "not_near_key_level",
        ],
        rule_version=LEVEL_VERSION,
    )
