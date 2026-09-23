"""D07/D09：组装 LangChain Agent，并校验结构化结果、记录运行终态。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
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

from stock_agent.agents.evidence import (
    collect_evidence_data_modes,
    validate_evidence,
    collect_evidence_ids,
)
from stock_agent.documents.sec_http import SEC_CLIENT
from stock_agent.storage.database import create_database_engine
from stock_agent.agents.context import ResearchContext
from stock_agent.agents.structured_output import (
    EvidenceValidationError,
    IncompleteResponseError,
)
from stock_agent.schemas.errors import make_public_error, map_error
from stock_agent.agents.langchain.langchain_tools import (
    build_langchain_tools,
    collect_tool_events,
)
from stock_agent.agents.langchain.tool_middleware import handle_tool_errors
from stock_agent.schemas.research import ResearchRequest

SYSTEM_PROMPT = """
你是只读的股票教学研究助手。

回答股票相关事实时，必须优先使用提供的工具获取证据，
不要仅依赖模型记忆回答公司事实。

对于收入、净利润、资产、股东权益等明确的结构化财务数值，
优先使用 Financial Tool，不要仅依靠 Filing 文本推测数值。

对于管理层解释、业务原因、风险因素、MD&A 等文本信息，
使用 Knowledge Tool。

如果用户的问题同时要求财务数值和文本解释，
可以同时调用 Financial Tool 和 Knowledge Tool。

工具使用规则：

1. 当问题涉及股票报价、价格或行情时，使用 get_quote。

2. 当问题涉及公司业务、产品、战略、风险、竞争情况、
   财报内容或其他公司文档信息时，使用 retrieve_knowledge。

3. 如果一个问题同时涉及报价和公司业务信息，
   可以同时使用 get_quote 和 retrieve_knowledge。

4. retrieve_knowledge 的 company_id 必须使用请求中的公司代码。
   question 应描述需要检索的具体信息。

5. 最终输出中的 facts 和 inferences 只能引用本轮工具实际返回的 evidence_id。

6. 如果现有工具返回的信息不足以回答问题，
   返回 insufficient_information，不要编造缺失事实。

7. 最终 data_mode 根据实际引用的证据填写：只引用一种模式就使用该模式；
   同时引用不同模式时使用 mixed；没有引用任何证据时使用 null。
"""


MAX_MODEL_ROUNDS = 3
MAX_TOOL_CALLS = 4

TASK_TIMEOUT_SECONDS = 300


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
        context_schema=ResearchContext,
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
    engine=None,
) -> dict[str, Any]:
    """运行 Agent。"""
    async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
        return await agent.ainvoke(
            build_agent_input(request),
            context=ResearchContext(
                as_of=request.as_of,
                engine=engine,
                sec_client=SEC_CLIENT,
                ),
        )


async def run_research(
    agent,
    request: ResearchRequest,
    engine=None,
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
                context=ResearchContext(
                        as_of=request.as_of,
                        engine=engine,
                        sec_client=SEC_CLIENT,
                    ),
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

        # print(
        #     json.dumps(
        #         output,
        #         ensure_ascii=False,
        #         indent=2,
        #         default=str,
        #     )
        # )

        try:
            allowed_ids = collect_evidence_ids(latest_state["messages"])
            evidence_modes = collect_evidence_data_modes(latest_state["messages"])
            if engine is None and any(
                evidence_id.startswith(("rag:", "financial:"))
                for evidence_id in allowed_ids
            ):
                engine = create_database_engine()
            validate_evidence(
                output,
                allowed_ids,
                evidence_modes,
                request.data_mode,
                engine=engine
            )
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
