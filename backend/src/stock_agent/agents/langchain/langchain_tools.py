"""D07 Step 4：把现有只读 TOOL_REGISTRY 暴露为 LangChain Tools。

本模块只能做协议适配。报价、公司资料、参数清理、NVDA 限制和 fixture 数据
继续由 execute_tool()、TOOL_REGISTRY 与现有 handler 负责。
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
from stock_agent.agents.context import ResearchContext
from stock_agent.retrieval.knowledge import retrieve_knowledge
from stock_agent.schemas.tool_params import CompanyToolParams, KnowledgeToolParams
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


@tool("get_quote", args_schema=CompanyToolParams)
async def get_quote_adapter(company_id: str) -> dict[str, object]:
    """只读；仅支持 NVDA，返回本地 fixture 教学模拟报价，不是实时行情。"""
    result = await execute_tool("get_quote", {"company_id": company_id})

    return {
        **result,
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

def build_langchain_tools() -> list[BaseTool]:
    """无输入；返回报价、公司资料与知识检索三个白名单工具。"""
    return [
        get_quote_adapter,
        get_company_profile_adapter,
        retrieve_knowledge_tool,
        get_financial_facts_tool,
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
