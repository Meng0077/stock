"""D04 整合练习占位，按 docs/day04.md 实现。

Task 2：请求与解析结构化输出（详见 docs/day04/02_structured_output.md）。
TODO 2.2：验证真实模型能否在同一请求中组合工具调用与 JSON 模式；
若不能，单独请求最终结果，并将该请求计入模型轮数预算。
TODO 2.3：记录完整工具往返的真实模型结果，与离线样例分开标记。

Task 5：模型请求、工具调用和整个任务分别限时；请求次数、工具次数与
输出 token 数均有上限，实际 token 用量写入本次运行事件。
Task 6：当前安装的 SDK 无原生 asyncio 客户端，使用 httpx.AsyncClient；
真实模型的工具调用与 JSON 模式组合仍待 API 限额恢复后验证。

后续任务 TODO：管理异步客户端、取消与清理，使用安全错误对象和事件记录。

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
from zai.types.chat.chat_completion import Completion
from dotenv import load_dotenv
import os
import uuid

from stock_agent.agents.evidence_validation import EvidenceValidationError, validate_evidence
from stock_agent.agents.tool_calling import (
    ToolCallProtocolError,
    build_tool_definitions,
    execute_tool_and_return,
)
from stock_agent.schemas.research_output import ResearchOutput



BACKEND = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = "你是股票分析助手。仅依据用户提供的资料回答，区分事实、推断和缺失信息。"
MAX_MODEL_ROUNDS=3
MAX_TOOL_CALLS=4
MAX_OUTPUT_TOKENS = 5000
TASK_TIMEOUT_SECONDS = 120
REFUSAL_PREFIXES = ("抱歉", "很抱歉", "对不起", "sorry", "i can't", "i cannot")


class BigModelAsyncClient:
    """通过普通 HTTP 对话接口发送可取消的异步请求。"""

    def __init__(self, *, api_key: str, timeout: float, transport=None):
        self._http = httpx.AsyncClient(
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self._http.__aexit__(exc_type, exc_value, traceback)

    async def create(self, **kwargs):
        response = await self._http.post("chat/completions", json=kwargs)
        response.raise_for_status()
        return Completion.model_validate(response.json())


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

async def model_loop(
    client, model, api_key, max_round=MAX_MODEL_ROUNDS, max_tool=MAX_TOOL_CALLS,
    events=None, model_timeout=30.0,
) -> int:
    if events is None:
        events = []
    run_messages = deepcopy(messages)
    allowed_ids: set[str] = set()
    expected_data_mode = "fixture"
    round = 0
    tool_calls_executed = 0
    run_id = str(uuid.uuid4())
    repair_used = False

    while round < max_round:
        round += 1
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
            events.append({"type": "model_timeout", "run_id": run_id, "round": round})
            print("模型请求超时。", file=sys.stderr)
            return 1
        except httpx.TimeoutException:
            events.append({"type": "model_timeout", "run_id": run_id, "round": round})
            print("模型请求超时。", file=sys.stderr)
            return 1

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
            return 1

        choice = choices[0]
        message = choice.message
        if choice.finish_reason not in ("stop", "tool_calls"):
            print("模型响应未正常完成", file=sys.stderr)
            return 1
        if getattr(message, "refusal", None) or is_refusal_text(message.content):
            print("模型拒答", file=sys.stderr)
            return 1
        if message.tool_calls:
            if repair_used:
                print('修复请求不该调用工具')
                return 1
            if round >= max_round:
                print("模型请求了工具调用，但已达到最大轮数，结束循环。")
                return 1
            if tool_calls_executed >= max_tool:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                return 1
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
                return 1
            if tool_calls_executed >= max_tool:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                return 1
            continue
        elif choice.finish_reason != "stop" or not message.content or not message.content.strip():
            print("未正常完成 或 响应错误：模型没有返回工具调用或可用正文")
            return 1
        else:
            content = message.content
            try:
                result = ResearchOutput.model_validate_json(content)
            except ValidationError as error:
                print("模型输出不符合 ResearchOutput", file=sys.stderr)

                if not repair_used:
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

                return 1
            try:
                validate_evidence(result, allowed_ids, expected_data_mode)
            except EvidenceValidationError as error:
                print(f"证据校验失败：{error}", file=sys.stderr)
                return 1
            return 0
    return 1



async def main(argv: list[str] | None = None, *, events=None) -> int:
    parser = argparse.ArgumentParser(description="D04 结构化研究 Agent 练习")
    parser.add_argument("--preview", action="store_true", help="离线展示模型输入、工具声明和输出 schema")
    args = parser.parse_args(argv)

    if args.preview:
        print(json.dumps({
            "messages": messages,
            "tools": build_tool_definitions(),
            "response_format": {"type": "json_object"},
            "research_output_schema": ResearchOutput.model_json_schema(),
        }, ensure_ascii=False, indent=2))
        return 0

    load_dotenv(BACKEND / ".env", override=False)
    api_key = os.getenv("ZHIPU_API_KEY", "").strip()
    model = os.getenv("MODEL_NAME", "").strip()
    if not api_key or not model:
        print("配置错误：请设置 ZHIPU_API_KEY 和 MODEL_NAME。", file=sys.stderr)
        return 1
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        print("配置错误：MODEL_TIMEOUT_SECONDS 必须是大于 0 的有限数字。", file=sys.stderr)
        return 1

    status = 1
    try:
        async with BigModelAsyncClient(api_key=api_key, timeout=timeout) as client:
            async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
                status = await model_loop(
                    client, model, api_key, events=events, model_timeout=timeout
                )
    except TimeoutError:
        print("任务总时限已到。", file=sys.stderr)
        status = 1
    except httpx.TimeoutException:
        print("模型请求超时。", file=sys.stderr)
        status = 1
    except httpx.HTTPStatusError:
        print("模型服务返回错误状态。", file=sys.stderr)
        status = 1
    except httpx.RequestError:
        print("模型连接失败。", file=sys.stderr)
        status = 1
    except (ValueError, ValidationError):
        print("模型响应解析失败。", file=sys.stderr)
        status = 1
    except Exception:
        print("模型调用失败；原始异常已隐藏。", file=sys.stderr)
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
