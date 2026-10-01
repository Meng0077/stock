from stock_agent.decision.factors import (
    evaluate_level,
    evaluate_momentum,
    evaluate_trend,
)
from stock_agent.decision.models import (
    DecisionResult,
    FactorOpinion,
    MarketContext,
    MarketView,
)


DECISION_VERSION = "decision-v1"


def _make_blocked_decision(
    *,
    context: MarketContext,
    missing_information: list[str],
    warnings: list[str],
    factors: list[FactorOpinion] | None = None,
) -> DecisionResult:
    return DecisionResult(
        symbol=context.symbol,
        as_of=context.as_of,
        status="blocked",
        market_view=None,
        rule_version=DECISION_VERSION,
        factors=factors or [],
        missing_information=missing_information,
        warnings=warnings,
    )


def _combine_market_view(
    factors: list[FactorOpinion],
) -> tuple[
    MarketView,
    list[str],
]:
    """
    把可用的 Trend / Momentum / Level
    综合成最终技术市场方向。

    规则：
    1. Trend + Momentum 是主要方向因子；
    2. Trend 是主要方向锚点，Momentum 同向时确认；
    3. Momentum mixed / neutral 不推翻明确 Trend，
       只有相反方向才形成 mixed；
    4. 如果只有一个主要方向因子可用，
       使用它作为 partial decision 的基础方向；
    5. Level 不通过投票决定方向，只负责：
       - 同方向确认；
       - 反方向 breakout / breakdown 制造冲突；
    6. 如果 Trend / Momentum 都不可用，
       才直接使用 Level。
    """

    usable_by_name = {
        factor.factor: factor
        for factor in factors
        if factor.status == "usable"
    }
    trend = usable_by_name.get("trend")
    momentum = usable_by_name.get("momentum")
    level = usable_by_name.get("level")
    decision_reasons: list[str] = []

    # --------------------------------------------------------
    # 1. Trend + Momentum 都存在
    # --------------------------------------------------------
    if trend is not None and momentum is not None:
        assert trend.signal is not None
        assert momentum.signal is not None

        # Trend 是整体方向的主要锚点。
        #
        # Momentum bullish / bearish 表示明确方向；
        # mixed / neutral 更多表示没有完成方向确认，
        # 不应该自动推翻已经形成的趋势结构。

        if trend.signal == "bullish":
            if momentum.signal == "bearish":
                # 趋势向上，但动能已经明确向下，
                # 属于真正的方向冲突。
                market_view: MarketView = "mixed"
                decision_reasons.append("trend_momentum_conflict")
            else:
                # bullish / mixed / neutral
                #
                # Momentum 如果没有明确转 bearish，
                # 保持当前 bullish Trend。
                market_view = "bullish"
                decision_reasons.append(
                    "primary_factors_aligned"
                    if momentum.signal == "bullish"
                    else "trend_direction_retained_without_momentum_confirmation"
                )
        elif trend.signal == "bearish":
            if momentum.signal == "bullish":
                # 趋势向下，但动能已经明确向上。
                market_view = "mixed"
                decision_reasons.append("trend_momentum_conflict")
            else:
                # bearish / mixed / neutral
                market_view = "bearish"
                decision_reasons.append(
                    "primary_factors_aligned"
                    if momentum.signal == "bearish"
                    else "trend_direction_retained_without_momentum_confirmation"
                )
        else:
            # Trend 本身还是 mixed，
            # 表示中期趋势结构尚未形成明确方向。
            #
            # Momentum 即使已经 bullish / bearish，
            # 也暂时不足以把整体市场结构升级成明确方向。
            market_view = "mixed"
            decision_reasons.append("trend_not_directional")

    # --------------------------------------------------------
    # 2. 只有 Trend 可用
    # --------------------------------------------------------
    elif trend is not None:
        assert trend.signal is not None
        market_view = trend.signal
        decision_reasons.append("trend_only_available")
    # --------------------------------------------------------
    # 3. 只有 Momentum 可用
    # --------------------------------------------------------
    elif momentum is not None:
        assert momentum.signal is not None
        market_view = momentum.signal
        decision_reasons.append("momentum_only_available")
    # --------------------------------------------------------
    # 4. 两个主要方向因子都不可用
    # --------------------------------------------------------
    elif level is not None:
        assert level.signal is not None
        # 此时只能依赖 Level。
        #
        # Decision 会是 partial，
        # 因此调用方仍然可以知道
        # Trend / Momentum 数据并不完整。
        return level.signal, ["level_only_available"]
    else:
        # 正常情况下不会走到这里：
        #
        # evaluate_market() 在调用本函数前，
        # 已经保证至少有一个 usable Factor。
        raise ValueError("no usable factor for market view")

    # --------------------------------------------------------
    # 5. Level 检查明确结构冲突
    # --------------------------------------------------------
    if level is None:
        return market_view, decision_reasons

    assert level.signal is not None

    # Level 只有 bullish / bearish
    # 才代表真正发生 breakout / breakdown。
    #
    # neutral：
    #   near support / resistance 等位置状态。
    #
    # mixed：
    #   key zone / tight range。
    #
    # 它们都不直接覆盖主要方向。

    # --------------------------------------------------------
    # 6. Level 与明确 bullish 主方向冲突
    # --------------------------------------------------------
    if market_view == "bearish" and level.signal == "bullish":
        decision_reasons.append("level_conflicts_with_primary_direction")
        return "mixed", decision_reasons

    # --------------------------------------------------------
    # 7. Level 与明确 bearish 主方向冲突
    # --------------------------------------------------------
    if market_view == "bullish" and level.signal == "bearish":
        decision_reasons.append("level_conflicts_with_primary_direction")
        return "mixed", decision_reasons

    # --------------------------------------------------------
    # 8. Level 与主方向一致
    # --------------------------------------------------------
    if market_view in {"bullish", "bearish"} and level.signal == market_view:
        decision_reasons.append("level_confirms_primary_direction")

    # --------------------------------------------------------
    # 9. Level 没有明确方向
    # --------------------------------------------------------
    elif level.signal in {"neutral", "mixed"}:
        decision_reasons.append("level_no_directional_override")

    # --------------------------------------------------------
    # 10. 主方向本身已经 mixed
    # --------------------------------------------------------
    elif market_view == "mixed":
        # 例如：
        #
        # Trend bullish
        # Momentum bearish
        # Level bullish
        #
        # Level 不负责通过“2 比 1 投票”
        # 消除 Trend / Momentum 的核心冲突。
        decision_reasons.append("level_does_not_resolve_primary_conflict")

    return market_view, decision_reasons


def _collect_opposing_reasons(
    market_view: MarketView,
    factors: list[FactorOpinion],
) -> list[str]:
    """
    收集当前最终方向已经存在的反面 / 未确认信息。

    opposing_reasons 只服务明确方向：
        bullish
        bearish

    mixed / neutral 本身已经代表没有形成单一方向，
    其原因由 decision_reasons + factors 解释，
    不再重复生成 opposing_reasons。
    """
    if market_view not in {
        "bullish",
        "bearish",
    }:
        return []

    usable_by_name = {
        factor.factor: factor
        for factor in factors
        if factor.status == "usable"
    }
    # trend = usable_by_name.get("trend")
    momentum = usable_by_name.get("momentum")
    level = usable_by_name.get("level")
    opposing_reasons: list[str] = []

    # --------------------------------------------------------
    # 1. Momentum 没有确认当前方向
    # --------------------------------------------------------
    if momentum is not None and momentum.signal in {"mixed", "neutral"}:
        # 无论是短中周期方向不一致，
        # 还是 Momentum 完全走平，
        # 都说明当前 Trend 没有得到完整动能确认。
        opposing_reasons.append("momentum_not_confirmed")

        # 保留 Factor 已经计算出的具体原因，
        # 这样 Agent 不需要自己猜为什么没确认。
        if "momentum_horizons_not_aligned" in momentum.reasons:
            opposing_reasons.append("momentum_horizons_not_aligned")

        if "returns_flat" in momentum.reasons:
            opposing_reasons.append("returns_flat")

    # --------------------------------------------------------
    # 2. Level 对 bullish 的反面位置因素
    # --------------------------------------------------------
    if market_view == 'bullish' and level is not None:
        # 靠近阻力不会直接把 bullish 改成 bearish，
        # 但属于当前上涨方向需要面对的结构障碍。
        if "near_resistance" in level.reasons:
            opposing_reasons.append("near_resistance")
        # 位于历史关键价格区域时，
        # 当前方向可能受到明显结构影响。
        if "at_key_price_zone" in level.reasons:
            opposing_reasons.append("at_key_price_zone")
        # 上下 support / resistance 都很近，
        # 表示价格处于窄结构区间。
        if "inside_tight_range" in level.reasons:
            opposing_reasons.append("inside_tight_range")
    # --------------------------------------------------------
    # 3. Level 对 bearish 的反面位置因素
    # --------------------------------------------------------
    if market_view == 'bearish' and level is not None:
        # 对 bearish 来说，
        # 下方 support 才是结构上的反面因素。
        if "near_support" in level.reasons:
            opposing_reasons.append("near_support")
        if "at_key_price_zone" in level.reasons:
            opposing_reasons.append("at_key_price_zone")
        if "inside_tight_range" in level.reasons:
            opposing_reasons.append("inside_tight_range")

    return opposing_reasons

def _has_evidence(
    factor: FactorOpinion,
    metric: str,
) -> bool:
    """判断 Factor 是否实际包含某项证据。"""
    return any(
        evidence.metric == metric
        for evidence in factor.evidence
    )

def _collect_invalidation_conditions(
    market_view: MarketView,
    decision_reasons: list[str],
    factors: list[FactorOpinion],
) -> list[str]:
    """
    描述哪些变化会使当前 Decision 的判断依据失效，
    从而要求重新评估。

    注意：
    invalidation 不要求 market_view 一定改变。

    即使 market_view 仍然是 mixed，
    只要 mixed 的形成原因发生变化，
    当前 Decision 也已经需要重新计算。
    """

    usable_by_name = {
        factor.factor: factor
        for factor in factors
        if factor.status == "usable"
    }
    trend = usable_by_name.get("trend")
    momentum = usable_by_name.get("momentum")
    level = usable_by_name.get("level")
    conditions: list[str] = []

    # --------------------------------------------------------
    # 1. Trend
    # --------------------------------------------------------
    if (
        market_view == "bullish"
        and trend is not None
        and trend.signal == "bullish"
    ):
        # 当前 bullish Trend 的核心定义是：
        #
        # price > MA20 > MA50
        # MA20 slope > 0
        # MA50 slope > 0
        #
        # 下面任意一个条件发生，
        # 当前 bullish Trend 都不再满足原规则。
        conditions.extend([
            "price_not_above_ma20",
            "ma20_not_above_ma50",
            "ma20_slope_non_positive",
            "ma50_slope_non_positive",
        ])
    elif (
        market_view == "bearish"
        and trend is not None
        and trend.signal == "bearish"
    ):
        conditions.extend([
            "price_not_below_ma20",
            "ma20_not_below_ma50",
            "ma20_slope_non_negative",
            "ma50_slope_non_negative",
        ])


    # --------------------------------------------------------
    # 2. Momentum
    # --------------------------------------------------------

    # Momentum mixed / neutral 不会推翻 Trend。
    #
    # 只有 Momentum 明确切换到相反方向，
    # 才会让 Day33 的最终 market_view 进入 mixed。
    if momentum is not None:
        if market_view == "bullish":
            conditions.append("momentum_turns_bearish")
        elif market_view == "bearish":
            conditions.append("momentum_turns_bullish")



    # --------------------------------------------------------
    # 3. Level
    # --------------------------------------------------------

    # Level 的明确方向只来自真正的
    # 20d high breakout / 20d low breakdown。
    #
    # 所以这里记录最明确的反方向结构事件。
    if level is not None:
        if market_view == "bullish" and _has_evidence(level, "recent_low_20d"):
            conditions.append("price_breaks_below_20d_low")
        elif market_view == "bearish" and _has_evidence(level, "recent_high_20d"):
            conditions.append("price_breaks_above_20d_high")

    # --------------------------------------------------------
    # 4. mixed:Trend / Momentum 明确冲突
    # --------------------------------------------------------
    if "trend_momentum_conflict" in decision_reasons:
        conditions.extend([
            "momentum_no_longer_opposes_trend",
            "trend_no_longer_opposes_momentum",
        ])

    # --------------------------------------------------------
    # 5. mixed：Trend 自己没有形成明确方向
    # --------------------------------------------------------
    if "trend_not_directional" in decision_reasons:
        conditions.extend([
            "trend_becomes_bullish",
            "trend_becomes_bearish",
        ])
    # --------------------------------------------------------
    # 6. mixed：Level 与主方向发生明确结构冲突
    # --------------------------------------------------------
    if "level_conflicts_with_primary_direction" in decision_reasons:
        conditions.extend([
            "level_no_longer_conflicts_with_primary_direction",
            "primary_direction_changes",
        ])

    # --------------------------------------------------------
    # 7. neutral：Momentum 本身走平
    # --------------------------------------------------------
    if (
        market_view == "neutral"
        and momentum is not None
        and momentum.signal == "neutral"
    ):
        # Momentum neutral 当前定义是：
        #
        # ROC5 == 0
        # ROC20 == 0
        #
        # 任意周期重新产生方向，
        # 当前 neutral momentum 就失效。
        conditions.extend([
            "return_5d_becomes_nonzero",
            "return_20d_becomes_nonzero",
        ])

    # --------------------------------------------------------
    # 8. neutral：Level 当前只是某种位置状态
    # --------------------------------------------------------

    if (
        market_view == "neutral"
        and level is not None
        and level.signal == "neutral"
    ):
        if "near_support" in level.reasons:
            conditions.append(
                "support_distance_exceeds_0_5_atr"
            )

        if "near_resistance" in level.reasons:
            conditions.append(
                "resistance_distance_exceeds_0_5_atr"
            )

        if (
            "not_near_key_level"
            in level.reasons
        ):
            conditions.append(
                "price_enters_key_level_proximity"
            )

    return conditions

def evaluate_market(
    context: MarketContext,
) -> DecisionResult:
    """
    根据 MarketContext 生成确定性的技术分析结果。

    整体流程：
        1. Guard 判断核心技术数据是否允许参与决策；
        2. 分别运行 Trend / Momentum / Level；
        3. 根据 Factor 结果判断 complete / partial；
        4. 综合可用 Factor 得到 market_view。

    Day33 不负责：
        - 获取行情；
        - 重新计算技术指标；
        - 重新验证 Quote / Bar schema；
        - 给 Macro 或 MarketReaction 做方向评分；
        - 预测上涨概率。
    """

    # Technical 是当前技术决策流程唯一真正必需的组件。
    #
    # Quote 可以不存在，因为 Technical 的 current_price
    # 可能来自 incomplete bar 或最近完成日的 close。
    #
    # Macro / MarketReaction 属于研究上下文，
    # Day33 不把它们作为技术决策的硬依赖。
    if context.technical is None:
        return _make_blocked_decision(
            missing_information=["technical_missing"],
            context=context,
            warnings=context.warnings,
        )

    technical_quality = context.component_quality_statuses["technical"]
    # rejected 表示上游已经明确判断这份技术数据
    # 不适合继续用于当前研究。
    #
    # 这里直接阻断，而不是让三个 Factor
    # 分别再判断一遍数据质量。
    if technical_quality == "rejected":
        return _make_blocked_decision(
            missing_information=["technical_quality_rejected"],
            warnings=context.warnings,
            context=context,
        )

    warnings = list(context.warnings)
    # degraded 仍然允许参与计算，
    # 但最终 Decision 要保留这个事实。
    if technical_quality == "degraded":
        warnings.append("technical_quality_degraded")
    elif technical_quality == "not_assessed":
        warnings.append("technical_quality_not_assessed")

    # 三个 Factor。
    trend = evaluate_trend(context)
    momentum = evaluate_momentum(context)
    level = evaluate_level(context)

    factors = [trend, momentum, level]
    usable_factors = [factor for factor in factors if factor.status == "usable"]
    missing_information = [
        reason
        for factor in factors
        if factor.status != "usable"
        for reason in factor.reasons
    ]

    if not usable_factors:
        decision_status = "blocked"
    elif len(usable_factors) < len(factors):
        decision_status = "partial"
    else:
        decision_status = "complete"

    # 根据 usable_factors 综合 market_view。
    # --------------------------------------------------------
    # 4. 没有任何 Factor 可以形成判断
    # --------------------------------------------------------
    if decision_status == "blocked":
        return _make_blocked_decision(
            missing_information=missing_information,
            context=context,
            warnings=warnings,
            factors=factors,
        )

    # --------------------------------------------------------
    # 5. 综合最终 market view
    # --------------------------------------------------------
    market_view, decision_reasons = _combine_market_view(factors)
    opposing_reasons = _collect_opposing_reasons(market_view, factors)
    invalidation_conditions = _collect_invalidation_conditions(
        market_view,
        decision_reasons,
        factors,
    )
    return DecisionResult(
        symbol=context.symbol,
        as_of=context.as_of,
        status=decision_status,
        market_view=market_view,
        decision_reasons=decision_reasons,
        factors=factors,
        missing_information=missing_information,
        warnings=warnings,
        opposing_reasons=opposing_reasons,
        invalidation_conditions=invalidation_conditions,
        rule_version=DECISION_VERSION,
    )
