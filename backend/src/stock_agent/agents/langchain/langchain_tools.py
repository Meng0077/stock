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

from stock_agent.agents.context import ResearchContext
from stock_agent.retrieval.knowledge import retrieve_knowledge
from stock_agent.schemas.tool_params import CompanyToolParams, KnowledgeToolParams
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
        company_id=company_id,
        question=question,
        as_of=runtime.context.as_of,
    )
    return json.dumps(result, ensure_ascii=False)


def build_langchain_tools() -> list[BaseTool]:
    """无输入；返回报价、公司资料与知识检索三个白名单工具。"""
    return [
        get_quote_adapter,
        get_company_profile_adapter,
        retrieve_knowledge_tool,

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
