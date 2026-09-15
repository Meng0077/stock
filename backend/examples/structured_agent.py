"""D04 整合练习占位，按 docs/day04.md 实现。

Task 2：请求与解析结构化输出（详见 docs/day04/02_structured_output.md）。
TODO 2.2：验证真实模型能否在同一请求中组合工具调用与 JSON 模式；
若不能，单独请求最终结果，并将该请求计入模型轮数预算。
TODO 2.3：记录完整工具往返的真实模型结果，与离线样例分开标记。

Task 5：模型请求、工具调用和整个任务分别限时；请求次数、工具次数与
输出 token 数均有上限，实际 token 用量写入本次运行事件。
Task 6：当前安装的 SDK 无原生 asyncio 客户端，使用 httpx.AsyncClient；
真实模型的工具调用与 JSON 模式组合仍待 API 限额恢复后验证。

Task 7 后续：将离线取消与清理演示接入一次真实 Agent 任务；取消信号
必须传播，客户端关闭后不能继续请求模型、调用工具或格式修复。
Task 8：按下方 TODO 统一安全错误对象与运行终态事件。

运行约定：PYTHONPATH=backend/src python backend/examples/structured_agent.py --preview
"""


import argparse
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import httpx
from pydantic import ValidationError
# from zai.types.chat.chat_completion import Completion
from dotenv import load_dotenv
import os
import uuid

from stock_agent.agents.evidence_validation import EvidenceValidationError, validate_evidence
from stock_agent.agents.preview import format_preview
from stock_agent.agents.tool_calling import (
    ToolCallProtocolError,
    build_tool_definitions,
    execute_tool_and_return,
)
from stock_agent.schemas.research_output import ResearchOutput
from stock_agent.schemas.errors import ErrorCode, make_public_error
from stock_agent.llm_client import LLMClient, get_llm_config



BACKEND = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = "你是股票分析助手。仅依据用户提供的资料回答，区分事实、推断和缺失信息。"
MAX_MODEL_ROUNDS=3
MAX_TOOL_CALLS=4
MAX_OUTPUT_TOKENS = 5000
TASK_TIMEOUT_SECONDS = 320
REFUSAL_PREFIXES = ("抱歉", "很抱歉", "对不起", "sorry", "i can't", "i cannot")


# class BigModelAsyncClient:
#     """通过普通 HTTP 对话接口发送可取消的异步请求。"""

#     def __init__(self, *, api_key: str, timeout: float, transport=None):
#         self._http = httpx.AsyncClient(
#             base_url="https://open.bigmodel.cn/api/paas/v4/",
#             headers={"Authorization": f"Bearer {api_key}"},
#             timeout=timeout,
#             transport=transport,
#         )

#     async def __aenter__(self):
#         await self._http.__aenter__()
#         return self

#     async def __aexit__(self, exc_type, exc_value, traceback):
#         await self._http.__aexit__(exc_type, exc_value, traceback)

#     async def create(self, **kwargs):
#         response = await self._http.post("chat/completions", json=kwargs)
#         print('_______XXXXXXXX!!!!!!')
        
        
#         response.raise_for_status()
#         print('_______XXXXXXXX!!!!!!')
        
#         return Completion.model_validate(response.json())


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
            """
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


def build_preview() -> dict[str, object]:
    """构造离线请求预览；无入参，返回消息、工具和输出格式声明。"""
    return {
        "messages": deepcopy(messages),
        "tools": build_tool_definitions(),
        "response_format": {"type": "json_object"},
        "research_output_schema": ResearchOutput.model_json_schema(),
    }


def record_run_finished(
    events: list[dict[str, object]], run_id: str, status: str,
    code: ErrorCode | None = None,
) -> None:
    """输入事件列表、运行 ID、状态和可选错误码；写入终态，返回 None。"""
    event: dict[str, object] = {
        "type": "run_finished", "run_id": run_id, "status": status,
    }
    if code is not None:
        event["error"] = make_public_error(code).model_dump()
    events.append(event)


async def model_loop(
    client, model, max_round=MAX_MODEL_ROUNDS, max_tool=MAX_TOOL_CALLS,
    events=None, model_timeout=300.0, *, initial_messages=None,
    initial_evidence_ids=None, result_sink=None, run_id=None,
) -> int:
    if events is None:
        events = []
    run_messages = deepcopy(messages if initial_messages is None else initial_messages)
    allowed_ids: set[str] = set(initial_evidence_ids or ())
    expected_data_mode = "fixture"
    round = 0
    tool_calls_executed = 0
    run_id = run_id or str(uuid.uuid4())
    repair_used = False

    def finish(status: str, code: ErrorCode | None = None) -> int:
        if result_sink is not None:
            result_sink["messages"] = deepcopy(run_messages)
        record_run_finished(events, run_id, status, code)
        return 0 if code is None else 1
    while round < max_round:
        round += 1
        try:
            print('(((((((())))))))')
            async with asyncio.timeout(model_timeout) as request_limit:
                print('(((((((())))))))')
                response = await client.create(
                    model=model,
                    messages=run_messages,
                    tools=build_tool_definitions(),
                    response_format={"type": "json_object"},
                    max_tokens=MAX_OUTPUT_TOKENS,
                )
                print('NNNNNNNN')
        except TimeoutError:
            print('+++++++')
            if not request_limit.expired():
                raise
            events.append({"type": "model_timeout", "run_id": run_id, "round": round})
            print("模型请求超时。", file=sys.stderr)
            return finish("failed", "model_timeout")
        except httpx.TimeoutException:
            print('+++++++!!!!!!')
            
            events.append({"type": "model_timeout", "run_id": run_id, "round": round})
            print("模型请求超时。", file=sys.stderr)
            return finish("failed", "model_timeout")
        except Exception as e:
            print('+++++++!!!!!!', e)
            
        
        print('_______', response)
        if getattr(response, "usage", None) is not None:
            usage = {}
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(response.usage, field, None)
                usage[field] = value if value is not None else "unavailable"
            events.append({
                "type": "model_usage",
                "run_id": run_id,
                "round": round,
                "usage": usage,
            })

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
                print('修复请求不该调用工具')
                return finish("failed", "invalid_tool_call")
            if round >= max_round:
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
        elif choice.finish_reason != "stop" or not message.content or not message.content.strip():
            print("未正常完成 或 响应错误：模型没有返回工具调用或可用正文")
            return finish("failed", "incomplete_response")
        else:
            content = message.content
            try:
                result = ResearchOutput.model_validate_json(content)
            except ValidationError as error:
                print("模型输出不符合 ResearchOutput", file=sys.stderr)

                if not repair_used:
                    if round >= max_round:
                        return finish("failed", "budget_exhausted")
                    repair_used = True
                    errors = error.errors(
                        include_input=False,
                        include_context=False,
                        include_url=False,
                    )
                    run_messages.append({
                        "role": "user",
                        "content":  json.dumps({
                            "instruction": "仅修正上一条回答的 JSON 格式和字段；不要编造事实或证据。只输出 JSON 对象。",
                            "original_answer": content,
                            "schema": ResearchOutput.model_json_schema(),
                            "errors": errors,
                        }, ensure_ascii=False)
                    })
                    continue
                error_types = {item["type"] for item in error.errors()}
                code: ErrorCode = (
                    "invalid_json" if "json_invalid" in error_types else "invalid_output"
                )
                return finish("failed", code)
            try:
                validate_evidence(result, allowed_ids, expected_data_mode)
            except EvidenceValidationError as error:
                print(f"证据校验失败：{error}", file=sys.stderr)
                code = (
                    "data_mode_mismatch"
                    if error.code == "data_mode_mismatch"
                    else "invalid_evidence"
                )
                return finish("failed", code)
            if result_sink is not None:
                result_sink["final_output"] = result.model_dump()
            return finish(result.status)
    return finish("failed", "budget_exhausted")


async def main(argv: list[str] | None = None, *, events=None) -> int:
    if events is None:
        events = []
    parser = argparse.ArgumentParser(description="D04 结构化研究 Agent 练习")
    parser.add_argument("--preview", action="store_true", help="离线展示模型输入、工具声明和输出 schema")
    args = parser.parse_args(argv)

    if args.preview:
        print(format_preview(build_preview()))
        return 0
    
    config = get_llm_config(BACKEND / ".env")
    if not config:
        return 1
    
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "300"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        print("配置错误：MODEL_TIMEOUT_SECONDS 必须是大于 0 的有限数字。", file=sys.stderr)
        return 1

    status = 1
    event_start = len(events)
    total_limit = None

    def finish_main_error(status: str, code: ErrorCode) -> None:
        """为本次 main 记录终态；若模型已记录，则更新那一条。"""
        for event in events[event_start:]:
            if event.get("type") == "run_finished":
                event["status"] = status
                event["error"] = make_public_error(code).model_dump()
                return
        run_id = next(
            (event["run_id"] for event in reversed(events[event_start:]) if "run_id" in event),
            None,
        ) or str(uuid.uuid4())
        record_run_finished(events, run_id, status, code)

    try:
        async with LLMClient(provider=config.provider, api_key=config.api_key, timeout=timeout) as client:
            async with asyncio.timeout(TASK_TIMEOUT_SECONDS) as total_limit:
                status = await model_loop(
                    client, config.model, events=events, model_timeout=timeout
                )
    except asyncio.CancelledError:
        events.append({"type": "cancelled"})
        finish_main_error("cancelled", "cancelled")
        raise
    except TimeoutError:
        if total_limit is not None and total_limit.expired():
            print("任务总时限已到。", file=sys.stderr)
            finish_main_error("failed", "total_timeout")
        else:
            print("模型调用失败；原始异常已隐藏。", file=sys.stderr)
            finish_main_error("failed", "model_error")
        status = 1
    except httpx.TimeoutException:
        print("模型请求超时。", file=sys.stderr)
        finish_main_error("failed", "model_timeout")
        status = 1
    except httpx.HTTPStatusError:
        print("模型服务返回错误状态。", file=sys.stderr)
        finish_main_error("failed", "model_error")
        status = 1
    except httpx.RequestError:
        print("模型连接失败。", file=sys.stderr)
        finish_main_error("failed", "model_error")
        status = 1
    except (ValueError, ValidationError):
        print("模型响应解析失败。", file=sys.stderr)
        finish_main_error("failed", "model_error")
        status = 1
    except Exception:
        print("模型调用失败；原始异常已隐藏。", file=sys.stderr)
        finish_main_error("failed", "model_error")
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
