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
import math
import os
from pathlib import Path
import sys
import uuid

from stock_agent.agents.manual_agent import (
    MAX_MODEL_ROUNDS,
    MAX_OUTPUT_TOKENS,
    MAX_TOOL_CALLS,
    REFUSAL_PREFIXES,
    SYSTEM_PROMPT,
    is_refusal_text,
    messages,
    model_loop,
    record_run_finished,
)
from stock_agent.agents.preview import format_preview
from stock_agent.agents.run_errors import (
    error_code_from_exception,
    safe_message_from_exception,
)
from stock_agent.agents.tool_calling import build_tool_definitions
from stock_agent.llm_client import LLMClient, get_llm_config
from stock_agent.schemas.errors import ErrorCode, make_public_error
from stock_agent.schemas.research_output import ResearchOutput


BACKEND = Path(__file__).resolve().parents[1]
TASK_TIMEOUT_SECONDS = 320


def build_preview() -> dict[str, object]:
    """构造离线请求预览；无入参，返回消息、工具和输出格式声明。"""
    return {
        "messages": deepcopy(messages),
        "tools": build_tool_definitions(),
        "response_format": {"type": "json_object"},
        "research_output_schema": ResearchOutput.model_json_schema(),
    }


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
        print(
            "配置错误：请设置受支持的 LLM_PROVIDER、对应 API Key 和 MODEL_NAME。",
            file=sys.stderr,
        )
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
        async with LLMClient(
            provider=config.provider,
            api_key=config.api_key,
            timeout=timeout,
        ) as client:
            async with asyncio.timeout(TASK_TIMEOUT_SECONDS) as total_limit:
                status = await model_loop(
                    client, config.model, events=events, model_timeout=timeout
                )
    except asyncio.CancelledError:
        events.append({"type": "cancelled"})
        finish_main_error("cancelled", "cancelled")
        raise
    except Exception as error:
        total_timeout_expired = total_limit is not None and total_limit.expired()
        code = error_code_from_exception(
            error,
            total_timeout_expired=total_timeout_expired,
        )
        print(
            safe_message_from_exception(
                error,
                total_timeout_expired=total_timeout_expired,
            ),
            file=sys.stderr,
        )
        finish_main_error("failed", code)
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
