"""D07 Step 4：把现有只读 TOOL_REGISTRY 暴露为 LangChain Tools。

本模块只做 LangChain 协议适配。公司资料继续复用教学 registry；报价通过
运行时注入的 MarketDataProvider 查询。
"""

import asyncio
import json
from typing import Annotated
from uuid import uuid4

from langchain.tools import BaseTool, tool, ToolRuntime
from langchain_core.tools import InjectedToolArg
from langchain.messages import AIMessage, ToolMessage
from pydantic import ConfigDict
from pydantic.json_schema import SkipJsonSchema

from stock_agent.financial.service import (
    FinancialPeriodType,
    get_financial_facts,
)
from stock_agent.macro.models.release import MacroReleaseType
from stock_agent.macro.release_builders import get_latest_release
from stock_agent.agents.context import ResearchContext
from stock_agent.quality.macro import check_required_macro_releases, validate_macro_snapshot
from stock_agent.quality.report import DataQualityReport
from stock_agent.retrieval.knowledge import retrieve_knowledge
from stock_agent.schemas.tool_params import (
    CompanyToolParams,
    KnowledgeToolParams,
    MacroToolParams,
)
from stock_agent.storage.database import create_database_engine
from stock_agent.tools.registry import execute_tool


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
    """查询截至本次研究时间可用的长桥股票报价。"""
    factory = runtime.context.market_provider_factory
    if factory is None:
        raise RuntimeError("MarketDataProvider is not configured")

    quote = await asyncio.to_thread(
        factory().get_quote,
        company_id,
        as_of=runtime.context.as_of,
    )
    if quote is None:
        return {
            "data_mode": "live",
            "symbol": company_id,
            "quote": None,
        }

    return {
        **quote.model_dump(mode="json"),
        "evidence_id": f"E-{uuid4().hex}",
    }


@tool("get_company_profile", args_schema=CompanyToolParams)
async def get_company_profile_adapter(company_id: str) -> dict[str, object]:
    """只读；仅支持 NVDA，返回本地 fixture 公司资料，不是实时数据。"""
    result = await execute_tool("get_company_profile", {"company_id": company_id})
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

    if release_type is None:
        rejected_ids = {
            result.target_id
            for result in macro_results
            if result.status == "rejected"
        }
        safe_releases = [
            release
            for release in snapshot.recent_releases
            if release.release_id not in rejected_ids
        ]

        safe_snapshot = snapshot.model_copy(
            update={"recent_releases": safe_releases}
        )

        quality_report = DataQualityReport(
            as_of=snapshot.as_of,
            results=macro_results,
            source_warnings=snapshot.warnings,
        )

        evidence_id = (
            "macro:snapshot:"
            f"{snapshot.as_of.isoformat()}"
        )
        return {
            "evidence_id": evidence_id,
            "data_mode": "historical",
            "snapshot": snapshot.model_dump(mode="json"),
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
                snapshot=snapshot,
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


    release = get_latest_release(snapshot, release_type)
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

def build_langchain_tools() -> list[BaseTool]:
    """无输入；返回 Agent 可调用的只读白名单工具。"""
    return [
        get_quote_adapter,
        get_company_profile_adapter,
        retrieve_knowledge_tool,
        get_financial_facts_tool,
        get_macro_snapshot_tool,
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
