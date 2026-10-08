import asyncio

from stock_agent.agents.context import (
    ResearchContext,
)
from stock_agent.agents.langgraph.state import (
    ResearchPlan,
    ResearchState,
)
from stock_agent.market.earnings import (
    get_earnings_releases,
    research_earnings_reaction,
    research_earnings_reactions,
)
from stock_agent.quality.quote import validate_quote
from stock_agent.schemas.research import (
    ResearchRequest,
)

from stock_agent.macro.release_builders import (
    get_latest_release,
)
from stock_agent.market_reaction.service import (
    research_event_reaction,
)
from stock_agent.quality.macro import (
    check_required_macro_releases,
    validate_macro_snapshot,
)

from stock_agent.market.errors import (
    MarketDataProviderError,
)
from stock_agent.quality.market_service import (
    GuardedMarketAnalysis,
    build_guarded_market_analysis,
)

from stock_agent.decision.engine import (
    evaluate_market as evaluate_market_decision,
)
from stock_agent.decision.models import (
    MarketContext,
)
from stock_agent.retrieval.knowledge import (
    retrieve_knowledge,
)

from stock_agent.financial.service import (
    get_financial_facts,
)
from stock_agent.storage.database import (
    create_database_engine,
)

from stock_agent.tools.company import (
    get_sec_company_profile,
)

from langgraph.runtime import Runtime
from stock_agent.quality.report import (
    DataQualityReport,
)

async def _get_market_provider(context: ResearchContext):
    factory = context.market_provider_factory
    if not factory:
        raise ValueError("MarketDataProvider is not configured.")
    provider = await asyncio.to_thread(factory)
    return provider

async def _get_macro_provider(context: ResearchContext):
    factory = context.macro_builder_factory
    if not factory:
        raise ValueError("MacroDataProvider is not configured.")
    return await asyncio.to_thread(factory)

async def research_earnings_results(
    *,
    plan: ResearchPlan,
    request: ResearchRequest,
    context: ResearchContext,
) -> dict[str, object]:
    """
    执行 Earnings 相关研究。

    支持：
    - 最近一次财报后的市场反应；
    - 最近若干次财报后的历史反应；
    - 两者同时请求。

    Planner 决定需要哪些能力；
    本函数只负责按确定性依赖关系执行。
    """

    need_latest = plan.needs_earnings_reaction
    need_history = plan.needs_earnings_reaction_history

    if not need_latest and not need_history:
        return {}

    results: dict[str, object] = {}
    latest_earnings = None

    # ---------------------------------------------
    # 1. 计算这次总共需要多少个 Earnings Event
    # ---------------------------------------------
    limit = 0

    if need_history:
        assert plan.earnings_reaction_history_limit is not None
        limit = plan.earnings_reaction_history_limit

    if need_latest:
        limit += 1

    # 2. Earnings
    earnings = await asyncio.to_thread(
        get_earnings_releases,
        symbol=request.company_id,
        as_of=context.as_of,
        limit=limit,
    )

    # 3. 根据 Plan 拆 latest / history
    latest_earnings = earnings[0] if earnings and need_latest else None
    history_earnings = earnings[1:] if earnings and need_history and need_latest else earnings

    # 4. 没有任何 earnings，就不需要 Market Provider
    if not earnings:
        results: dict[str, object] = {}
        if need_latest:
            results["earnings_reaction"] = None

        if need_history:
            results["earnings_reaction_history"] = []
            results["earnings_release_history"] = []

        return results

    # 5. Market Provider
    provider = await _get_market_provider(context)

    results: dict[str, object] = {}
    # 6. Latest Reaction
    if need_latest:
        results["earnings_release"] = latest_earnings
        if latest_earnings is None:
            results["earnings_reaction"] = None
        else:
            assert provider is not None
            reaction = await asyncio.to_thread(
                research_earnings_reaction,
                earnings=latest_earnings,
                symbol=request.company_id,
                as_of=context.as_of,
                provider=provider,
            )
            results["earnings_reaction"] = reaction

    # 7. Historical Reactions
    if need_history:
        results["earnings_release_history"] = history_earnings

        assert provider is not None
        historical_reactions = await asyncio.to_thread(
            research_earnings_reactions,
            earnings=history_earnings,
            symbol=request.company_id,
            as_of=context.as_of,
            provider=provider,
        )
        results["earnings_reaction_history"] = historical_reactions

    return results

async def research_macro_results(
    *,
    plan: ResearchPlan,
    context: ResearchContext,
    symbol: str,
) -> dict[str, object]:
    """
    执行 Macro 相关研究。

    当前支持：
    - 完整 MacroSnapshot；
    - 指定类型的最近一次 MacroReleaseEvent；
    - 指定最近一次 Release 的市场反应。

    Historical Macro Reaction 后续单独处理。
    """

    if not plan.needs_macro:
        return {}


    provider = await _get_macro_provider(context)

    # 1. 构建 Macro Snapshot
    snapshot = await asyncio.to_thread(
        provider.build_latest,
        as_of=context.as_of,
    )

    # 2. Snapshot 数据质量
    quality_results = validate_macro_snapshot(snapshot=snapshot, strict_pit=False)

    release_type = plan.macro_release_type
    # 如果用户明确要求某一种宏观事件，
    # 还要检查该 release 是否缺失。
    if release_type is not None:
        quality_results.extend(
            check_required_macro_releases(snapshot=snapshot, required_types={release_type}),
        )

    quality_report = DataQualityReport(
        as_of=context.as_of,
        results=quality_results,
        source_warnings=snapshot.warnings,
    )

    results: dict[str, object] = {
        "macro_snapshot": snapshot,
        "macro_quality": quality_report,
    }


    # 3. 没指定 release type，到完整 Snapshot 就结束。
    if release_type is None:
        return results

    # 4. 选择指定类型最近一次 Release
    release = get_latest_release(snapshot, release_type)
    results["macro_release"] = release

    needs_latest_reaction = plan.needs_macro_reaction
    needs_history_reaction = plan.needs_macro_reaction_history
    if not needs_latest_reaction and not needs_history_reaction:
        return results

    # 准备 latest reaction
    latest_release_for_reaction = None
    if needs_latest_reaction:
        if release is None:
            results["macro_reaction"] = None
        else:
            release_quality = next(
                    (
                        quality
                        for quality in quality_results
                        if (
                            quality.target_id
                            == release.release_id
                        )
                    ),
                    None,
                )
            if release_quality is not None and release_quality.status == 'rejected':
                results["macro_reaction"] = None
            else:
                latest_release_for_reaction = release

    # 准备 historical releases
    history_releases = []
    if needs_history_reaction:
        history_limit = plan.macro_reaction_history_limit
        assert history_limit is not None
        history_before = None
        # 同时请求“这次 + 过去 N 次”时，
        # 历史部分排除 latest。
        if needs_latest_reaction and release is not None:
            history_before = release.release_date
        history_releases, history_warnings = await asyncio.to_thread(
            provider.build_release_history,
            release_type=release_type,
            limit=history_limit,
            before=history_before,
            as_of=context.as_of,
        )

        results["macro_release_history"] = history_releases
        results["macro_history_warnings"] = history_warnings

    # 没有任何 Reaction 可以计算
    if latest_release_for_reaction is None and not history_releases:
        if needs_history_reaction:
            results["macro_reaction_history"] = []
        return results

    # Reaction 才需要 Market Provider
    market_provider = await _get_market_provider(context)

    # Latest Reaction
    if latest_release_for_reaction is not None:
        latest_reaction = await asyncio.to_thread(
            research_event_reaction,
            release=latest_release_for_reaction,
            symbol=symbol,
            provider=market_provider,
            as_of=context.as_of,
        )

        results["macro_reaction"] = latest_reaction

    # Historical Reactions
    if needs_history_reaction:
        history_reactions = []
        for history_release in history_releases:
            history_reaction = await asyncio.to_thread(
                research_event_reaction,
                release=history_release,
                symbol=symbol,
                provider=market_provider,
                as_of=context.as_of,
            )
            history_reactions.append(history_reaction)
        results["macro_reaction_history"] = history_reactions


    return results

async def load_market_analysis(
    *,
    symbol: str,
    context: ResearchContext,
) -> tuple[
    GuardedMarketAnalysis,
    list[str],
]:
    """
    获取一次市场基础分析。

    负责：
    - 获取 Quote；
    - 获取 250 根完成的日 K；
    - 隔离 Quote / Bars Provider 失败；
    - 执行统一 Market Quality Guard；
    - 构建 Technical Snapshot。

    不负责：
    - 决定是否把 Quote 暴露给 results；
    - 决定是否把 Technical 暴露给 results；
    - 生成 Decision；
    - Agent evidence 序列化。
    """
    provider = await _get_market_provider(context)
    source_warnings: list[str] = []

    assert provider is not None
    # quote
    try:
        quote = await asyncio.to_thread(
            provider.get_quote,
            symbol=symbol,
            as_of=context.as_of,
        )
    except MarketDataProviderError:
        quote = None

        source_warnings.append(
            "quote_provider_unavailable"
        )

    # bars
    try:
        bars = await asyncio.to_thread(
            provider.get_bars,
            symbol=symbol,
            as_of=context.as_of,
            timeframe="1d",
            limit=250,
            include_incomplete=False,
        )
    except MarketDataProviderError:
        bars = []

        source_warnings.append(
            "bars_provider_unavailable"
        )

    # Quality Guard + Technical
    analysis = build_guarded_market_analysis(
        symbol=symbol,
        quote=quote,
        bars=bars,
        as_of=context.as_of,
        market_state=context.market_state,
    )

    return analysis, source_warnings

async def research_market_results(
    *,
    plan: ResearchPlan,
    context: ResearchContext,
    symbol: str,
) -> dict[str, object]:
    """
    执行 Quote / Technical / Decision
    共用的市场研究。

    执行策略：

    Quote only:
        只查询 Quote。

    Technical / Decision:
        Quote + Daily Bars 只加载一次，
        Technical / Decision / Quote
        共用 GuardedMarketAnalysis。
    """
    needs_market_analysis = plan.needs_technical or plan.needs_decision
    needs_quote = plan.needs_quote
    source_warnings = []

    if not needs_quote and not needs_market_analysis:
        return {}

    #  Quote-only
    if needs_quote and not needs_market_analysis:
        provider = await _get_market_provider(context)
        try:
            quote = await asyncio.to_thread(
                provider.get_quote,
                symbol=symbol,
                as_of=context.as_of,
            )
        except MarketDataProviderError:
            quote = None
            source_warnings.append(
                "quote_provider_unavailable"
            )
        quote_quality = validate_quote(
            quote=quote,
            symbol=symbol,
            as_of=context.as_of,
            market_state=(
                context.market_state
            ),
        )
        quality_report = DataQualityReport(
            as_of=context.as_of,
            results=[quote_quality],
            source_warnings=source_warnings,
        )

        safe_quote = quote if quote_quality.status != "rejected" else None
        return {
            "quote": safe_quote,
            "market_quality": (
                quality_report
            ),
        }

    analysis, source_warnings = await load_market_analysis(symbol=symbol, context=context)
    quality_report = DataQualityReport(
        as_of=context.as_of,
        results=analysis.quality.results,
        source_warnings=source_warnings
    )
    results: dict[str, object] = {
        "market_quality": quality_report,
    }
    # quote
    if plan.needs_quote:
        results["quote"] = analysis.current_quote

    # 1.technical
    if plan.needs_technical:
        results["technical"] = analysis.technical

    # 2. Decision
    if plan.needs_decision:
        market_context = MarketContext(
            symbol=symbol,
            as_of=context.as_of,
            # Decision 内部实际依赖 Quote + Technical。
            #
            # 这里描述的是 Decision 使用的上下文，
            # 不是 Planner 的输出字段。
            requested_components={"quote", "technical"},
            quote=analysis.current_quote,
            technical=analysis.technical,
            quality_report=quality_report,
            warnings=source_warnings,
        )
        decision = evaluate_market_decision(context=market_context)
        results["decision"] = decision

    return results


async def research_knowledge_results(
    *,
    plan: ResearchPlan,
    context: ResearchContext,
    company_id: str,
) -> dict[str, object]:
    """
    执行公司文档知识检索。

    Planner 负责决定：
        是否需要 Knowledge；
        具体要检索什么问题。

    Executor 只负责：
        按 plan 中已经确定的问题执行检索；
        保留检索到的 evidence。

    不负责：
        重新理解用户问题；
        修改 knowledge_question；
        根据检索内容生成结论。
    """
    question = plan.knowledge_question
    if question is None:
        return {}

    normalized_company_id = company_id.strip().upper()
    knowledge = await asyncio.to_thread(
        retrieve_knowledge,
        normalized_company_id,
        question,
        context.as_of,
        engine=context.engine,
        config=context.index_config,
    )
    return {
        "knowledge": knowledge
    }

async def research_financial_results(
    *,
    plan: ResearchPlan,
    context: ResearchContext,
    company_id: str,
) -> dict[str, object]:
    """
    执行 Planner 已确定的结构化财务查询。

    Planner 负责：
    - concept；
    - unit；
    - period_type。

    Executor 负责：
    - 按这些参数调用 Financial Service；
    - 保持 request 与 facts 的对应关系。

    不负责：
    - 猜测 XBRL concept；
    - 解析 SEC Company Facts JSON；
    - 自己计算同比 / 环比 / TTM；
    - 重新执行 as_of / period filtering。
    """
    financial_requests = plan.financial_requests
    if not financial_requests:
        return {}

    # 多个 financial request 共用同一个 Engine。
    engine = context.engine
    if engine is None:
        engine = await asyncio.to_thread(
            create_database_engine
        )
    normalized_company_id = company_id.strip().upper()
    financial_results: list[ dict[str, object] ] = []

    for request in financial_requests:
        facts = await asyncio.to_thread(
            get_financial_facts,
            engine=engine,
            client=context.sec_client,
            company_id=normalized_company_id,
            concept=request.concept,
            unit=request.unit,
            as_of=context.as_of.date(),
            period_type=request.period_type,
        )

        # 与当前 LangChain Financial Tool
        # 保持一致：只把最近 4 个期间交给 Agent。
        facts = facts[:4]
        financial_results.append({
            "concept": request.concept,
            "unit": request.unit,
            "period_type": request.period_type,
            "facts": facts,
        })


    return {
        "financial": financial_results
    }


async def research_company_profile_results(
    *,
    plan: ResearchPlan,
    company_id: str,
) -> dict[str, object]:
    """
    查询 Planner 明确要求的公司基础资料。

    这里只负责：
    - 根据 needs_company_profile 决定是否执行；
    - 规范化 company_id；
    - 调用现有 Company Profile 业务函数。

    不负责：
    - Tool 白名单校验；
    - 生成 ToolMessage；
    - 生成随机 evidence_id；
    - 把 fixture 数据伪装成实时公司资料。
    """
    if not plan.needs_company_profile:
        return {}

    normalized_company_id = company_id.strip().upper()
    company_profile = await asyncio.to_thread(
        get_sec_company_profile,
        normalized_company_id
    )
    return {
        "company_profile": company_profile
    }

async def research_node(
    state: ResearchState,
    runtime: Runtime[ResearchContext],
) -> dict[str, object]:
    """
    根据 ResearchPlan 执行研究能力，
    并把新结果合并进 ResearchState.results。

    当前节点只负责编排；
    不实现任何具体业务计算。
    """
    request = state["request"]
    plan = state["plan"]
    if plan is None:
        raise RuntimeError("research plan is missing")

    context = runtime.context

    # 保留之前已经成功得到的结果。
    #
    # 后续 checker 如果要求补充研究，
    # research 节点再次进入时，
    # 不应该把已有成功结果全部丢掉。
    results = dict(state.get("results", {}))

    company_id = request.company_id.strip().upper()

    # Company Profile
    company_results = await research_company_profile_results(
        plan=plan,
        company_id=company_id,
    )
    results.update(company_results)

    # Earnings
    earnings = await research_earnings_results(
        plan=plan,
        request=request,
        context=context,
    )
    results.update(earnings)

    # Macro
    macro = await research_macro_results(
        plan=plan,
        symbol=company_id,
        context=context,
    )
    results.update(macro)

    # market
    market = await research_market_results(
        plan=plan,
        symbol=company_id,
        context=context,
    )
    results.update(market)

    # Knowledge
    knowledge = await research_knowledge_results(
        plan=plan,
        company_id=company_id,
        context=context,
    )
    results.update(knowledge)

    # Financial
    financial = await research_financial_results(
        plan=plan,
        company_id=company_id,
        context=context,
    )
    results.update(financial)


    retry_count = state.get("retry_count", 0)
    if state.get("research_status") == "retry":
        retry_count += 1

    return {
        "results": results,
        "retry_count": retry_count,
    }
