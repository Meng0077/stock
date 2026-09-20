"""Manual Agent 的 provider-neutral 工具调用与结构化输出循环。

本模块是 CLI、离线评估器和 FastAPI runner 共用的唯一循环实现。它负责：
- 调用传入的异步模型客户端；
- 执行白名单工具并维护调用预算；
- 解析 ResearchOutput 并校验证据归属；
- 记录用量、错误和最终运行事件；
- 把消息历史和最终结果写入可选的 result_sink。

本模块不读取环境变量、不创建模型客户端，也不处理 HTTP 请求。
"""

import asyncio
from copy import deepcopy
import json
import sys
import uuid

import httpx
from pydantic import ValidationError

from stock_agent.agents.structured_output import (
    EvidenceValidationError,
    validate_evidence,
)
from stock_agent.agents.tool_calling import (
    ToolCallProtocolError,
    build_tool_definitions,
    execute_tool_and_return,
)
from stock_agent.schemas.errors import ErrorCode, make_public_error
from stock_agent.schemas.research_output import ResearchOutput


SYSTEM_PROMPT = "你是股票分析助手。仅依据用户提供的资料回答，区分事实、推断和缺失信息。"
MAX_MODEL_ROUNDS = 3
MAX_TOOL_CALLS = 4
MAX_OUTPUT_TOKENS = 5000
REFUSAL_PREFIXES = ("抱歉", "很抱歉", "对不起", "sorry", "i can't", "i cannot")


def is_refusal_text(content: str | None) -> bool:
    """识别没有结构化拒答字段时常见的纯文本拒答开头。"""
    if not isinstance(content, str):
        return False
    return content.strip().casefold().startswith(REFUSAL_PREFIXES)


messages = [
    {
        "role": "system",
        "content": f"""
            你是一个教学研究助手。
            查询公司资料或报价时，请使用提供的工具。
            工具返回的是本地模拟数据，不能描述为实时行情。
            尚未取得工具结果时，不要编造报价。
            请按照以下 JSON Schema 格式返回:
            {json.dumps(ResearchOutput.model_json_schema(), ensure_ascii=False)}
            """,
    },
    {
        "role": "user",
        "content": f"""
            请查询 NVDA 的教学模拟报价和公司介绍。
            请按照以下 JSON Schema 格式返回:
            {json.dumps(ResearchOutput.model_json_schema(), ensure_ascii=False)}
        """,
    },
]


def record_run_finished(
    events: list[dict[str, object]],
    run_id: str,
    status: str,
    code: ErrorCode | None = None,
) -> None:
    """输入事件列表、运行 ID、状态和可选错误码；写入终态，返回 None。"""
    event: dict[str, object] = {
        "type": "run_finished",
        "run_id": run_id,
        "status": status,
    }
    if code is not None:
        event["error"] = make_public_error(code).model_dump()
    events.append(event)


async def model_loop(
    client,
    model,
    max_round=MAX_MODEL_ROUNDS,
    max_tool=MAX_TOOL_CALLS,
    events=None,
    model_timeout=300.0,
    *,
    initial_messages=None,
    initial_evidence_ids=None,
    result_sink=None,
    run_id=None,
) -> int:
    """执行 Manual Agent 循环；返回进程式状态码，并写入事件与可选结果容器。"""
    if events is None:
        events = []
    run_messages = deepcopy(messages if initial_messages is None else initial_messages)
    allowed_ids: set[str] = set(initial_evidence_ids or ())
    expected_data_mode = "fixture"
    round_number = 0
    tool_calls_executed = 0
    run_id = run_id or str(uuid.uuid4())
    repair_used = False

    def finish(status: str, code: ErrorCode | None = None) -> int:
        if result_sink is not None:
            result_sink["messages"] = deepcopy(run_messages)
        record_run_finished(events, run_id, status, code)
        return 0 if code is None else 1

    while round_number < max_round:
        round_number += 1
        try:
            async with asyncio.timeout(model_timeout) as request_limit:
                response = await client.create(
                    model=model,
                    messages=run_messages,
                    tools=build_tool_definitions(),
                    response_format={"type": "json_object"},
                    max_tokens=MAX_OUTPUT_TOKENS,
                )
        except TimeoutError:
            if not request_limit.expired():
                raise
            events.append(
                {
                    "type": "model_timeout",
                    "run_id": run_id,
                    "round": round_number,
                }
            )
            print("模型请求超时。", file=sys.stderr)
            return finish("failed", "model_timeout")
        except httpx.TimeoutException:
            events.append(
                {
                    "type": "model_timeout",
                    "run_id": run_id,
                    "round": round_number,
                }
            )
            print("模型请求超时。", file=sys.stderr)
            return finish("failed", "model_timeout")

        if getattr(response, "usage", None) is not None:
            usage = {}
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(response.usage, field, None)
                usage[field] = value if value is not None else "unavailable"
            events.append(
                {
                    "type": "model_usage",
                    "run_id": run_id,
                    "round": round_number,
                    "usage": usage,
                }
            )

        choices = response.choices
        if not choices:
            print("模型没有返回结果")
            return finish("failed", "incomplete_response")

        choice = choices[0]
        message = choice.message
        if choice.finish_reason not in ("stop", "tool_calls"):
            print("模型响应未正常完成", file=sys.stderr)
            return finish("failed", "incomplete_response")
        if getattr(message, "refusal", None) or is_refusal_text(message.content):
            print("模型拒答", file=sys.stderr)
            return finish("failed", "model_refusal")
        if message.tool_calls:
            if repair_used:
                print("修复请求不该调用工具")
                return finish("failed", "invalid_tool_call")
            if round_number >= max_round:
                print("模型请求了工具调用，但已达到最大轮数，结束循环。")
                return finish("failed", "budget_exhausted")
            if tool_calls_executed >= max_tool:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                return finish("failed", "budget_exhausted")
            try:
                tool_calls_executed = await execute_tool_and_return(
                    message,
                    messages=run_messages,
                    events=events,
                    run_id=run_id,
                    tool_calls_executed=tool_calls_executed,
                    max_tools=max_tool,
                    allowed_ids=allowed_ids,
                )
            except ToolCallProtocolError as error:
                print(f"工具调用协议错误：{error}", file=sys.stderr)
                return finish("failed", "invalid_tool_call")
            if tool_calls_executed >= max_tool:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                return finish("failed", "budget_exhausted")
            continue
        if choice.finish_reason != "stop" or not message.content or not message.content.strip():
            print("未正常完成 或 响应错误：模型没有返回工具调用或可用正文")
            return finish("failed", "incomplete_response")

        content = message.content
        try:
            result = ResearchOutput.model_validate_json(content)
        except ValidationError as error:
            print("模型输出不符合 ResearchOutput", file=sys.stderr)

            if not repair_used:
                if round_number >= max_round:
                    return finish("failed", "budget_exhausted")
                repair_used = True
                errors = error.errors(
                    include_input=False,
                    include_context=False,
                    include_url=False,
                )
                run_messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "instruction": "仅修正上一条回答的 JSON 格式和字段；不要编造事实或证据。只输出 JSON 对象。",
                                "original_answer": content,
                                "schema": ResearchOutput.model_json_schema(),
                                "errors": errors,
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue
            error_types = {item["type"] for item in error.errors()}
            code: ErrorCode = (
                "invalid_json" if "json_invalid" in error_types else "invalid_output"
            )
            return finish("failed", code)

        try:
            validate_evidence(
                result,
                allowed_ids,
                {
                    evidence_id: "fixture"
                    for evidence_id in allowed_ids
                },
                expected_data_mode,
            )
        except EvidenceValidationError as error:
            print(f"证据校验失败：{error}", file=sys.stderr)
            code = (
                "data_mode_mismatch"
                if error.code in {"data_mode_mismatch", "data_mode_not_allowed"}
                else "invalid_evidence"
            )
            return finish("failed", code)

        if result_sink is not None:
            result_sink["final_output"] = result.model_dump()
        return finish(result.status)

    return finish("failed", "budget_exhausted")
