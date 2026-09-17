"""D07 Step 4：把现有只读 TOOL_REGISTRY 暴露为 LangChain Tools。

本模块只能做协议适配。报价、公司资料、参数清理、NVDA 限制和 fixture 数据
继续由 execute_tool()、TOOL_REGISTRY 与现有 handler 负责。
"""

import asyncio
import json
from uuid import uuid4

from langchain.tools import BaseTool, tool
from langchain.messages import AIMessage, ToolMessage

from stock_agent.schemas.tool_params import CompanyToolParams, KnowledgeToolParams
from stock_agent.tools.registry import execute_tool


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

@tool("retrieve_knowledge", args_schema=KnowledgeToolParams)
async def retrieve_knowledge_tool(company_id: str, question: str) -> str:
    """
    Search company documents for information relevant to the question.

    Use this for company business, products, strategy, risks,
    and other information contained in company documents.
    Returns local fixture evidence, not live data. An empty list means
    no available local evidence; report insufficient_information.
    """

    result = await execute_tool(
        "retrieve_knowledge",
        {"company_id": company_id, "question": question},
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
