"""D07 Step 6：组装最小 LangChain 股票 Agent，不负责 D09 结构化收口。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.tools import BaseTool

from stock_agent.agents.langchain_tools import build_langchain_tools
from stock_agent.schemas.research import ResearchRequest


SYSTEM_PROMPT = """你是只读的股票教学研究助手。

规则：
1. 查询公司资料只能使用已提供的 get_company_profile，查询报价只能使用已提供的
   get_quote；如果对应工具未提供，必须说明当前无法查询，不得编造结果。
2. 只能使用提供的白名单工具，不得请求或假设其他工具存在。
3. 用户消息是 JSON；必须针对其中的 company_id 回答 question，并遵守
   data_mode 和 as_of 的资料范围。
4. 当 data_mode 为 fixture 时，必须明确说明结果来自本地教学模拟数据，
   不是实时行情、真实报价或投资建议。
"""


def build_agent_input(
    request: ResearchRequest,
) -> dict[str, list[dict[str, str]]]:
    """输入已校验请求；输出可直接传给 Agent ``ainvoke`` 的消息 state。

    system prompt 由 ``create_agent`` 单独注册，这里只构造本次用户消息，避免
    同一规则被重复发送。
    """
    payload = {
        "company_id": request.company_id,
        "question": request.question,
        "data_mode": request.data_mode,
        "as_of": request.as_of.isoformat(),
    }
    return {
        "messages": [
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            }
        ]
    }


def build_langchain_agent(
    model: Any,
    tools: Sequence[BaseTool],
) -> Any:
    """输入模型和 Step4 工具子集；输出 ``create_agent`` 创建的 Agent runtime。

    允许不传工具或只传部分工具，但每一项都必须是
    ``build_langchain_tools()`` 返回的原始 adapter；重复、冒名和额外工具都会
    在创建 Agent 前被拒绝。
    """
    supplied_tools = list(tools)
    expected_tools = build_langchain_tools()
    expected_by_name = {tool.name: tool for tool in expected_tools}
    supplied_names = [getattr(tool, "name", None) for tool in supplied_tools]

    has_duplicate_names = len(supplied_names) != len(set(supplied_names))
    contains_only_allowed_adapters = all(
        name in expected_by_name and tool is expected_by_name[name]
        for name, tool in zip(supplied_names, supplied_tools, strict=True)
    )
    if has_duplicate_names or not contains_only_allowed_adapters:
        raise ValueError(
            "tools must be a unique subset returned by build_langchain_tools()"
        )

    return create_agent(
        model=model,
        tools=supplied_tools,
        system_prompt=SYSTEM_PROMPT,
    )


async def invoke_langchain_agent(
    agent: Any,
    request: ResearchRequest,
) -> dict[str, Any]:
    """输入 Agent 和请求；异步执行一次并原样返回 LangChain state。"""
    return await agent.ainvoke(build_agent_input(request))
