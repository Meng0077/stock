"""D07/D09：组装 LangChain Agent，并校验结构化结果、记录运行终态。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
    wrap_model_call,
)
from langchain.messages import AIMessage

from stock_agent.agents.structured_output import (
    EvidenceValidationError,
    IncompleteResponseError,
    collect_evidence_ids,
    validate_evidence,
)
from stock_agent.schemas.errors import make_public_error, map_error
from stock_agent.agents.langchain.langchain_tools import (
    build_langchain_tools,
    collect_tool_events,
)
from stock_agent.agents.langchain.tool_middleware import handle_tool_errors
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
5. 工具拒绝查询或没有所需资料时，不得换成其他公司的数据或编造结果。
   如果要求结构化输出，应返回 status="insufficient_information"，并在
   missing_information 中说明缺少的资料；无资料时 facts 和 inferences 为空。
"""


MAX_MODEL_ROUNDS = 3
MAX_TOOL_CALLS = 4

TASK_TIMEOUT_SECONDS = 20


@wrap_model_call
async def reject_truncated_response(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    """模型节点提交结果前拒绝截断，不继续工具执行或下一轮格式修复。"""
    response = await handler(request)
    for message in response.result:
        if isinstance(message, AIMessage) and message.response_metadata.get("finish_reason") == "length":
            raise IncompleteResponseError("模型响应被截断")
    return response


def build_agent_input(
    request: ResearchRequest,
) -> dict[str, list[dict[str, str]]]:
    """把 ResearchRequest 转成 Agent 输入。"""
    
    return {
        "messages": [
            {
                "role": "user",
                "content": request.model_dump_json(),
            }
        ]
    }


def build_langchain_agent(
    model: Any,
    response_format = None
) -> Any:
    """创建 LangChain Agent，内部提供固定的报价和公司资料工具。"""

    return create_agent(
        model=model,
        tools=build_langchain_tools(),
        system_prompt=SYSTEM_PROMPT,
        response_format=response_format,
        middleware=[
                handle_tool_errors,
                ModelCallLimitMiddleware(
                    run_limit=MAX_MODEL_ROUNDS,
                    exit_behavior="error"
                ),
                ToolCallLimitMiddleware(
                    run_limit=MAX_TOOL_CALLS,
                    exit_behavior="error"
                ),
                reject_truncated_response,
            ],
        
    )


async def invoke_langchain_agent(
    agent: Any,
    request: ResearchRequest,
) -> dict[str, Any]:
    """运行 Agent。"""
    async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
        return await agent.ainvoke(
            build_agent_input(request)
        )


async def run_research(
    agent,
    request: ResearchRequest,
):
    """运行边界：统一返回运行身份、终态、结果、安全错误和事件。"""
    run_id = str(uuid.uuid4())
    events = [{"type": "run_started", "run_id": run_id}]
    latest_state = build_agent_input(request)
    runtime_error = None

    try:
        async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
            async for state in agent.astream(
                latest_state,
                stream_mode="values",
            ):
                latest_state = state
    # 此运行边界负责把 runtime 异常转换成不含原始异常的公开失败。
    except Exception as error:
        runtime_error = error

    events.extend(collect_tool_events(latest_state["messages"], run_id))
    output = None
    public_error = None

    if runtime_error is not None:
        public_error = make_public_error(map_error(runtime_error)).model_dump()
    else:
        output = latest_state["structured_response"]
        allowed_ids = collect_evidence_ids(latest_state["messages"])
        try:
            validate_evidence(output, allowed_ids, request.data_mode)
        except EvidenceValidationError as error:
            public_error = make_public_error(map_error(error)).model_dump()
            output = None

    status = "failed" if public_error is not None else output.status
    events.append({
        "type": "run_finished",
        "run_id": run_id,
        "status": status,
        "error": public_error,
    })

    return {
        "run_id": run_id,
        "status": status,
        "output": output,
        "error": public_error,
        "events": events,
    }
