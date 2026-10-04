"""D07 Step 4：把现有只读 TOOL_REGISTRY 暴露为 LangChain Tools。

本模块只做 LangChain 协议适配。公司资料继续复用教学 registry；报价通过
运行时注入的 MarketDataProvider 查询。
"""

import asyncio
import json
from typing import Annotated, cast
from uuid import uuid4

from langchain.tools import BaseTool, tool, ToolRuntime
from langchain_core.tools import InjectedToolArg
from langchain.messages import AIMessage, ToolMessage
from pydantic import ConfigDict, TypeAdapter
from pydantic.json_schema import SkipJsonSchema

from stock_agent.financial.service import (
    FinancialPeriodType,
    get_financial_facts,
)
from stock_agent.macro.models.release import MacroReleaseType
from stock_agent.macro.release_builders import get_latest_release
from stock_agent.macro.temporal import (
    filter_releases_as_of,
    validate_release_as_of,
)
from stock_agent.agents.context import ResearchContext
from stock_agent.market.errors import MarketDataProviderError
from stock_agent.quality.macro import check_required_macro_releases, validate_macro_snapshot
from stock_agent.quality.market_service import build_guarded_market_analysis
from stock_agent.quality.report import DataQualityReport
from stock_agent.retrieval.knowledge import retrieve_knowledge
from stock_agent.schemas.tool_params import (
    CompanyToolParams,
    KnowledgeToolParams,
    MacroToolParams,
    MarketReactionToolParams,
)
from stock_agent.storage.database import create_database_engine
from stock_agent.tools.registry import execute_tool
from stock_agent.quality.quote import validate_quote
from stock_agent.decision.engine import (
    evaluate_market as evaluate_market_decision,
)
from stock_agent.decision.models import (
    MarketContext,
)

from stock_agent.market_reaction.service import (
    research_event_reaction,
)

from stock_agent.market_reaction.models import (
    MarketReactionResult,
)

class KnowledgeToolRuntimeParams(KnowledgeToolParams):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    runtime: Annotated[
        SkipJsonSchema[ToolRuntime[ResearchContext]],
        InjectedToolArg,
    ]


class MacroToolRuntimeParams(MacroToolParams):
    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    runtime: Annotated[
        SkipJsonSchema[ToolRuntime[ResearchContext]],
        InjectedToolArg,
    ]


class QuoteToolRuntimeParams(CompanyToolParams):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    runtime: Annotated[
        SkipJsonSchema[ToolRuntime[ResearchContext]],
        InjectedToolArg,
    ]


@tool("get_quote", args_schema=QuoteToolRuntimeParams)
async def get_quote_adapter(
    company_id: str,
    runtime: ToolRuntime[ResearchContext],
) -> dict[str, object]:
    """获取经过质量检查的股票报价。"""

    factory = runtime.context.market_provider_factory
    if factory is None:
        raise RuntimeError("MarketDataProvider is not configured")

    as_of = runtime.context.as_of
    symbol = company_id.strip().upper()

    quote = await asyncio.to_thread(
        factory().get_quote,
        company_id,
        as_of=runtime.context.as_of,
    )

    # 无论是否取得报价，都执行质量检查
    quality = validate_quote(
        quote=quote,
        symbol=symbol,
        as_of=as_of,
        market_state=runtime.context.market_state,
    )

    # 保持与 Macro Tool 一致的质量报告结构
    quality_report = DataQualityReport(
        as_of=as_of,
        results=[quality],
    )

    #  拒绝的数据不能进入 Agent 的事实证据
    if quality.status == "rejected":
        return {
            "symbol": symbol,
            "as_of": as_of.isoformat(),
            "quote": None,
            "quality": quality_report.model_dump(
                mode="json"
            ),
        }

    #  usable / degraded 均可展示，
    # 但 degraded 必须附带限制说明。
    assert quote is not None

    return {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "data_mode": quote.data_mode,
        "quote": quote.model_dump(mode="json"),
        "evidence_id": f"E-{uuid4().hex}",
        "quality": quality_report.model_dump(
            mode="json"
        ),
    }


@tool("get_company_profile", args_schema=CompanyToolParams)
async def get_company_profile_adapter(company_id: str) -> dict[str, object]:
    """只读；仅支持 NVDA，返回本地 fixture 公司资料，不是实时数据。"""
    result = cast(
        dict[str, object],
        await execute_tool(
            "get_company_profile",
            {"company_id": company_id},
        ),
    )
    return {
        **result,
        "evidence_id": f"E-{uuid4().hex}",
    }

@tool("retrieve_knowledge", args_schema=KnowledgeToolRuntimeParams)
async def retrieve_knowledge_tool(
    company_id: str,
    question: str,
    runtime: ToolRuntime[ResearchContext],
) -> str:
    """
    Search company documents for information relevant to the question.

    Use this for company business, products, strategy, risks,
    and other information contained in company documents.
    Returns SEC filing evidence available by the request's as_of time.
    An empty list means no available evidence; report insufficient_information.
    """
    result = retrieve_knowledge(
        engine=runtime.context.engine,
        company_id=company_id,
        question=question,
        as_of=runtime.context.as_of,
        config=runtime.context.index_config,
    )
    return json.dumps(result, ensure_ascii=False)


@tool("get_financial_facts")
def get_financial_facts_tool(
    company_id: str,
    # cik: str,
    concept: str,
    unit: str,
    period_type: FinancialPeriodType,
    runtime: ToolRuntime[ResearchContext],
) -> dict[str, object]:
    """查询公司的结构化 SEC 财务事实。

    Args:
        company_id:
            公司标识，例如 "NVDA"。

        concept:
            XBRL concept，例如：
            "NetIncomeLoss"
            "Assets"
            "RevenueFromContractWithCustomerExcludingAssessedTax"

        unit:
            数值单位，例如：
            "USD"
            "shares"
            "USD/shares"

        period_type:
            财务事实类型：
            "quarterly"
            "annual"
            "instant"
            "all"

        runtime:
            LangChain 注入的运行时上下文。

            其中包含：
            - SEC client
            - as_of

            这个参数不暴露给模型。

    Returns:
        结构化财务事实列表。

    这个 Tool 负责：
        - 接收模型给出的财务查询参数。
        - 从 runtime 获取 as_of 和 SEC client。
        - 调用 Financial service。
        - 转成适合 ToolMessage 序列化的 dict。

    这个 Tool 不负责：
        - 自己解析 SEC JSON。
        - 自己计算同比、环比或 TTM。
        - 猜测用户真正想问哪个 concept。
    """

    engine = runtime.context.engine or create_database_engine()
    facts = get_financial_facts(
        engine=engine,
        client=runtime.context.sec_client,
        company_id=company_id,
        concept=concept,
        unit=unit,
        as_of=runtime.context.as_of.date(),
        period_type=period_type,
    )

    recent_facts = facts[-4:]

    return {
            "data_mode": "historical",
            "facts": [
                {
                    "evidence_id": fact.fact_id,
                    **fact.model_dump(mode="json")
                }
                for fact in recent_facts
            ]
        }


@tool("get_macro_snapshot", args_schema=MacroToolRuntimeParams)
def get_macro_snapshot_tool(
    runtime: ToolRuntime[ResearchContext],
    release_type: MacroReleaseType | None = None,
) -> dict[str, object]:
    """查询截至本次研究时间的宏观快照或最近一次指定发布事件。

    release_type 可选值为 cpi、ppi、pce、employment_situation、
    weekly_claims；不传时返回完整 MacroSnapshot，包括 Fed、SEP 和美债。
    """

    factory = runtime.context.macro_builder_factory
    if factory is None:
        raise RuntimeError("MacroSnapshotBuilder is not configured")


    snapshot = factory().build_latest(as_of=runtime.context.as_of)
    macro_results = validate_macro_snapshot( snapshot=snapshot, strict_pit=False,)
    safe_releases, _ = filter_releases_as_of(
        snapshot.recent_releases,
        as_of=snapshot.as_of,
        strict_pit=False,
    )
    safe_snapshot = snapshot.model_copy(
        update={"recent_releases": safe_releases}
    )

    if release_type is None:
        quality_report = DataQualityReport(
            as_of=safe_snapshot.as_of,
            results=macro_results,
            source_warnings=safe_snapshot.warnings,
        )

        evidence_id = (
            "macro:snapshot:"
            f"{safe_snapshot.as_of.isoformat()}"
        )
        return {
            "evidence_id": evidence_id,
            "data_mode": "historical",
            "snapshot": safe_snapshot.model_dump(mode="json"),
            "quality": quality_report.model_dump(mode="json"),
        }


    if release_type is not None:
        # 只汇总本次明确请求的发布类型。
        macro_results = [
            result
            for result in macro_results
            if any(
                release.release_id == result.target_id
                and release.release_type == release_type
                for release in snapshot.recent_releases
            )
        ]

        macro_results.extend(
            check_required_macro_releases(
                snapshot=safe_snapshot,
                required_types={release_type},
            )
        )

    quality_report = DataQualityReport(
        as_of=snapshot.as_of,
        results=macro_results,
        # 单一发布的报告暂不混入其他宏观模块的警告。
        source_warnings=(
            snapshot.warnings
            if release_type is None
            else []
        ),
    )


    release = get_latest_release(safe_snapshot, release_type)
    if release is None:
        return {
            "data_mode": "historical",
            "release_type": release_type,
            "release": None,
            "quality": quality_report.model_dump(mode="json"),
            "warnings": snapshot.warnings,
        }

    # 先检查所选发布有没有被拒绝，再决定是否返回其数值
    release_quality = next(
        (
            result
            for result in macro_results
            if result.target_id == release.release_id
        ),
        None,
    )

    if release_quality is None or release_quality.status == "rejected":
        return {
            "data_mode": "historical",
            "release_type": release_type,
            "release": None,
            "quality": quality_report.model_dump(mode="json"),
            "warnings": snapshot.warnings,
        }

    return {
        "evidence_id": f"macro:{release.release_id}",
        "data_mode": "historical",
        "as_of": snapshot.as_of.isoformat(),
        "release": release.model_dump(mode="json"),
        "quality": quality_report.model_dump(mode="json"),
        "warnings": snapshot.warnings,
    }

@tool("get_technical_analysis", args_schema=QuoteToolRuntimeParams)
async def get_technical_analysis_tool(
    company_id: str,
    runtime: ToolRuntime[ResearchContext],
) -> dict[str, object]:
    """获取经过质量检查的日线技术指标及可用报价。

    返回 MA、ATR、收益率、价格结构、成交量特征，
    以及 Quote / Bars 各自的质量检查结果。
    """

    factory = runtime.context.market_provider_factory

    if factory is None:
        raise RuntimeError(
            "MarketDataProvider is not configured"
        )

    symbol = company_id.strip().upper()
    as_of = runtime.context.as_of

    provider = await asyncio.to_thread(factory)

    source_warnings: list[str] = []

    # ---------- 1. 获取 Quote ----------

    try:
        quote = await asyncio.to_thread(
            provider.get_quote,
            symbol,
            as_of=as_of,
        )
    except MarketDataProviderError:
        # Quote 失败，不应该阻止历史 K 线分析。
        quote = None
        source_warnings.append(
            "quote_provider_unavailable"
        )

    # ---------- 2. 获取历史日 K ----------
    try:
        bars = await asyncio.to_thread(
            provider.get_bars,
            symbol,
            as_of=as_of,
            timeframe="1d",
            limit=250,
            include_incomplete=False,
        )
    except MarketDataProviderError:
        # Bars 失败，不应该删除已经获取的有效 Quote。
        bars = []
        source_warnings.append(
            "bars_provider_unavailable"
        )

    # ---------- 3. 执行 Guard ----------

    analysis = build_guarded_market_analysis(
        symbol=symbol,
        quote=quote,
        bars=bars,
        as_of=as_of,
        market_state=runtime.context.market_state,
    )

    # ---------- 4. 处理报价证据 ----------
    quote_payload = None

    if analysis.current_quote is not None:
        safe_quote = analysis.current_quote

        quote_payload = {
            "evidence_id": (
                f"market:quote:{uuid4().hex}"
            ),
            "data_mode": safe_quote.data_mode,
            "value": safe_quote.model_dump(
                mode="json"
            ),
        }
    # ---------- 5. 处理技术分析证据 ----------
    technical_payload = None

    if analysis.technical is not None:
        # 明确技术指标所依据的历史数据来源。
        completed_modes = {
            bar.data_mode
            for bar in bars
            if bar.is_complete
        }

        if len(completed_modes) == 1:
            technical_mode = next(
                iter(completed_modes)
            )

            technical_payload = {
                "evidence_id": (
                    f"market:technical:{uuid4().hex}"
                ),
                "data_mode": technical_mode,
                "snapshot": (
                    analysis.technical.model_dump(
                        mode="json"
                    )
                ),
            }
        else:
            # 避免为混合来源的数据错误标记证据模式。
            source_warnings.append(
                "bars_data_mode_mixed"
            )

    # ---------- 6. 汇总质量报告 ----------

    quality_report = DataQualityReport(
        as_of=as_of,
        results=analysis.quality.results,
        source_warnings=source_warnings,
    )

    return {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "quote": quote_payload,
        "technical": technical_payload,
        "quality": quality_report.model_dump(
            mode="json"
        ),
    }

@tool(
    "evaluate_market",
    args_schema=QuoteToolRuntimeParams,
)
async def evaluate_market_tool(
    company_id: str,
    runtime: ToolRuntime[ResearchContext],
) -> dict[str, object]:
    """
    对股票当前技术状态执行确定性的 Decision Engine。

    适用于：
    - 当前走势怎么看；
    - 当前技术面偏多还是偏空；
    - 趋势和动能是否一致；
    - 当前观点有哪些反对因素；
    - 什么条件会让当前判断失效。

    不适用于：
    - 查询单个 MA / RSI 数值；
    - 查询财务数据；
    - 判断 CPI 后的历史市场反应。

    最终 market_view 由 Decision Engine 决定，
    Agent 只能解释，不能自行覆盖。

    quote + technical report(bar + quote => analysis => report) => decision + evidence => result
    """
    factory = runtime.context.market_provider_factory

    if factory is None:
        raise RuntimeError("MarketDataProvider is not configured")

    symbol = company_id.strip().upper()
    as_of = runtime.context.as_of
    provider = await asyncio.to_thread(factory)

    source_warnings: list[str] = []

    # 1. Quote
    try:
        quote = await asyncio.to_thread(
            provider.get_quote,
            symbol,
            as_of=as_of
        )
    except MarketDataProviderError:
        # Quote 获取失败并不代表整个技术分析失败。
        #
        # 如果历史 Bars 可用，
        # Decision 仍可以基于最近完成收盘价形成结果，
        # 但必须保留 warning。
        quote = None
        source_warnings.append("quote_provider_unavailable")

    # 2. Daily Bars
    try:
        bars = await asyncio.to_thread(
            provider.get_bars,
            symbol,
            as_of=as_of,
            timeframe="1d",
            # MA200 + slope 需要比 200 更长一点的窗口。
            limit=250,
            include_incomplete=False
        )
    except MarketDataProviderError:
        bars = []
        source_warnings.append("bars_provider_unavailable")

    # 3. Quality Guard + Technical Snapshot
    analysis = build_guarded_market_analysis(
        symbol=symbol,
        quote=quote,
        bars=bars,
        as_of=as_of,
        market_state=runtime.context.market_state,
    )

    # Tool 自己产生的 Provider warning
    # 和 Quality Report 分开保留。
    quality_report = DataQualityReport(
        as_of=as_of,
        results=analysis.quality.results,
        source_warnings=source_warnings,
    )

    # 4. MarketContext
    context = MarketContext(
        symbol=symbol,
        as_of=as_of,
        requested_components={"quote", "technical"},
        # rejected Quote 已经在 Guard 阶段被清空。
        quote=analysis.current_quote,
        technical=analysis.technical,
        quality_report=quality_report,
        warnings=source_warnings,
    )

    # 5. Deterministic Decision
    decision = evaluate_market_decision(context)

    # 6. Evidence：Quote
    quote_payload = None
    if analysis.current_quote is not None:
        safe_quote = analysis.current_quote

        quote_payload = {
            "evidence_id": f"market:quote:{uuid4().hex}",
            "data_mode": safe_quote.data_mode,
            "value": safe_quote.model_dump(mode="json")
        }

    # 7. Evidence：Technical
    technical_payload = None
    if analysis.technical is not None:
        completed_modes = {bar.data_mode for bar in bars if bar.is_complete}

        if len(completed_modes) == 1:
            technical_mode = next(iter(completed_modes))

            technical_payload = {
                "evidence_id": f"market:technical:{uuid4().hex}",
                "data_mode": technical_mode,
                "snapshot": analysis.technical.model_dump(mode="json")
            }
        else:
            source_warnings.append("bars_data_mode_mixed")

    # 8. 返回完整 DecisionResult
    return {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "decision": decision.model_dump(mode="json"),
        "quote": quote_payload,
        "technical": technical_payload,
        "quality": quality_report.model_dump(mode="json"),
    }


MARKET_REACTION_ADAPTER = TypeAdapter(MarketReactionResult)


class MarketReactionToolRuntimeParams(
    MarketReactionToolParams
):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    runtime: Annotated[
        SkipJsonSchema[
            ToolRuntime[ResearchContext]
        ],
        InjectedToolArg,
    ]


@tool("get_market_reaction", args_schema=MarketReactionToolRuntimeParams)
async def get_market_reaction_tool(
    company_id: str,
    release_id: str,
    runtime: ToolRuntime[ResearchContext],
) -> dict[str, object]:
    """
    查询某次已确认宏观发布之后，
    指定股票实际发生的市场反应。

    返回事件前参考价以及：
    - T+5m
    - T+30m
    - T+1h
    - close

    等观察窗口。

    本工具描述的是事件前后的实际市场变化，
    不能据此声称宏观事件与价格变化存在确定因果关系。
    """
    macro_factory = runtime.context.macro_builder_factory
    if macro_factory is None:
        raise RuntimeError("MacroSnapshotBuilder is not configured")

    market_factory = runtime.context.market_provider_factory
    if market_factory is None:
        raise RuntimeError("MarketDataProvider is not configured")

    symbol = company_id.strip().upper()
    normalized_release_id = release_id.strip()
    as_of = runtime.context.as_of

    # 1. 获取当前 as_of 下可见的 MacroSnapshot
    macro_provider = await asyncio.to_thread(macro_factory)
    snapshot = await asyncio.to_thread(
        macro_provider.build_latest,
        as_of=as_of
    )

    # 2. 通过 release_id 找具体事件
    release = next(
        (
            item
            for item in snapshot.recent_releases
            if item.release_id
            == normalized_release_id
        ),
        None,
    )

    # 3. 再做一次 as_of 过滤。
    # Market Reaction 只需要发布事件，
    # 不依赖该事件的宏观指标是否齐全。
    warnings: list[str] = []
    if release is not None:
        validation = validate_release_as_of(
            release,
            as_of=as_of,
            strict_pit=False,
        )
        if validation.decision == "reject":
            warnings.append(
                f"{release.release_id}:{validation.reason}"
            )
            release = None
        elif validation.decision == "usable_with_warning":
            warnings.append(
                f"{release.release_id}:{validation.reason}"
            )

    if release is None:
        return {
            "symbol": symbol,
            "release_id": (
                normalized_release_id
            ),
            "as_of": as_of.isoformat(),

            # 没有找到可用于当前 as_of
            # 的事件，因此不能产生 Reaction。
            "reaction": None,

            "warnings": [
                *snapshot.warnings,
                *warnings,
                "release_not_available_as_of",
            ],
        }

    # 4. 获取 Market Provider
    market_provider = await asyncio.to_thread(market_factory)

    # 5. reaction
    reaction = await asyncio.to_thread(
        research_event_reaction,
        release=release,
        symbol=symbol,
        provider=market_provider,
        as_of=as_of,
    )

    # 6. 返回完整结构化结果

    return {
        "evidence_id": (
            "market-reaction:"
            f"{normalized_release_id}:"
            f"{symbol}"
        ),

        # Market Reaction 查询的是已经发生的
        # 历史事件及其后续行情。
        "data_mode": "historical",

        "symbol": symbol,
        "release_id": (
            normalized_release_id
        ),
        "as_of": as_of.isoformat(),

        "reaction": (
            MARKET_REACTION_ADAPTER
            .dump_python(
                reaction,
                mode="json",
            )
        ),

        "warnings": [
            *snapshot.warnings,
            *warnings,
        ],
    }

def build_langchain_tools() -> list[BaseTool]:
    """无输入；返回 Agent 可调用的只读白名单工具。"""
    return [
        get_quote_adapter,
        get_company_profile_adapter,
        retrieve_knowledge_tool,
        get_financial_facts_tool,
        get_macro_snapshot_tool,
        get_technical_analysis_tool,
        evaluate_market_tool,
        get_market_reaction_tool,
    ]

def collect_tool_events(messages, run_id: str) -> list[dict]:
    events = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                events.append({
                    "type": "tool_requested",
                    "run_id": run_id,
                    "tool": call["name"],
                    "tool_call_id": call["id"],
                })
        elif isinstance(message, ToolMessage):
            events.append({
                "type": "tool_failed" if message.status == 'error' else "tool_succeeded",
                "run_id": run_id,
                "tool": message.name,
                "tool_call_id": message.tool_call_id,
            })
    return events


if __name__ == "__main__":
    result = asyncio.run(retrieve_knowledge_tool.ainvoke(
        {
            "company_id": "NVDA",
            "question": (
                "What drives NVIDIA's "
                "data center business?"
            ),
        }
    ))

    print(result)
