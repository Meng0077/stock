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
) -> MarketView:
    """
    把可用的 Trend / Momentum / Level
    综合成最终技术市场方向。

    规则：
    1. Trend + Momentum 是主要方向因子；
    2. 两者同方向才形成完整 bullish / bearish；
    3. 两者发生冲突或其中一个 mixed / neutral，
       结果为 mixed；
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
            else:
                # bullish / mixed / neutral
                #
                # Momentum 如果没有明确转 bearish，
                # 保持当前 bullish Trend。
                market_view = "bullish"
        elif trend.signal == "bearish":
            if momentum.signal == "bullish":
                # 趋势向下，但动能已经明确向上。
                market_view = "mixed"
            else:
                # bearish / mixed / neutral
                market_view = "bearish"
        else:
            # Trend 本身还是 mixed，
            # 表示中期趋势结构尚未形成明确方向。
            #
            # Momentum 即使已经 bullish / bearish，
            # 也暂时不足以把整体市场结构升级成明确方向。
            market_view = "mixed"

    # --------------------------------------------------------
    # 2. 只有 Trend 可用
    # --------------------------------------------------------
    elif trend is not None:
        assert trend.signal is not None
        market_view = trend.signal
    # --------------------------------------------------------
    # 3. 只有 Momentum 可用
    # --------------------------------------------------------
    elif momentum is not None:
        assert momentum.signal is not None
        market_view = momentum.signal
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
        return level.signal
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
        return market_view

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
    if market_view == "bearish" and level.signal == "bullish":
        return "mixed"
    if market_view == "bullish" and level.signal == "bearish":
        return "mixed"

    return market_view


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
    market_view = _combine_market_view(factors)
    return DecisionResult(
        symbol=context.symbol,
        as_of=context.as_of,
        status=decision_status,
        market_view=market_view,
        factors=factors,
        missing_information=missing_information,
        warnings=warnings,
        rule_version=DECISION_VERSION,
    )
