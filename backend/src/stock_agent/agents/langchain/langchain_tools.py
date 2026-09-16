"""D07 Step 4：把现有只读 TOOL_REGISTRY 暴露为 LangChain Tools。

本模块只能做协议适配。报价、公司资料、参数清理、NVDA 限制和 fixture 数据
继续由 execute_tool()、TOOL_REGISTRY 与现有 handler 负责。
"""

from uuid import uuid4

from langchain.tools import BaseTool, tool
from langchain.messages import AIMessage, ToolMessage

from stock_agent.schemas.tool_params import CompanyToolParams
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


def build_langchain_tools() -> list[BaseTool]:
    """无输入；输出恰好包含两个白名单 adapter 的 LangChain Tool 列表。"""
    return [
        get_quote_adapter,
        get_company_profile_adapter,
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
        
