"""LangChain 工具的业务拒绝和单次执行超时处理。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from langchain.agents.middleware import ToolCallRequest, wrap_tool_call
from langchain.messages import ToolMessage
from langgraph.types import Command

from stock_agent.agents.tool_calling import TOOL_TIMEOUT_SECONDS
from stock_agent.tools.errors import UnsupportedCompanyError
from stock_agent.macro.errors import MacroDataProviderError


MACRO_TOOL_TIMEOUT_SECONDS = 90


@wrap_tool_call
async def handle_tool_errors(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
) -> ToolMessage | Command[Any]:
    """成功结果原样返回；预期失败转成错误消息，取消和程序错误不捕获。

    未知工具和参数错误已由默认工具节点处理，不重复校验。
    """
    try:
        timeout_seconds = (
            MACRO_TOOL_TIMEOUT_SECONDS
            if request.tool_call["name"] == "get_macro_snapshot"
            else TOOL_TIMEOUT_SECONDS
        )
        async with asyncio.timeout(timeout_seconds) as tool_limit:
            return await handler(request)
    except UnsupportedCompanyError as error:
        code = "tool_rejected"
        message = f"{error}。该工具目前只支持 NVDA 的本地教学数据。"
    except httpx.TimeoutException:
        code = "tool_timeout"
        message = "工具的数据请求超时，未获得所需资料。"
    except TimeoutError:
        if not tool_limit.expired():
            raise
        code = "tool_timeout"
        message = "工具执行超时，未获得所需资料。"
    except MacroDataProviderError:
        code = "data_unavailable"
        message = "宏观数据源暂不可用，未取得所需资料。"

    return ToolMessage(
        content=json.dumps(
            {"ok": False, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        ),
        name=request.tool_call["name"],
        tool_call_id=request.tool_call["id"],
        status="error",
    )
