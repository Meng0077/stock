#!/usr/bin/env bash

set -eu

STOCK_SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
STOCK_BACKEND_DIR="$(CDPATH= cd -- "$STOCK_SCRIPT_DIR/.." && pwd)"
export STOCK_BACKEND_DIR
export PYTHONPATH="$STOCK_BACKEND_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$STOCK_BACKEND_DIR/.venv/bin/python" - <<'PY'
import asyncio
import json
import os
from pathlib import Path

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek

from stock_agent.agents.langchain.langchain_agent import (
    build_langchain_agent,
    invoke_langchain_agent,
)
from stock_agent.agents.langchain.langchain_tools import build_langchain_tools
from stock_agent.llm_client import get_llm_config
from stock_agent.schemas.research import ResearchRequest


BACKEND = Path(os.environ["STOCK_BACKEND_DIR"])


def safe_tool_result(message: ToolMessage) -> dict[str, object]:
    """只保留 fixture 的公开字段，不输出内部对象。"""
    content = message.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return {"parseable": False}
    if not isinstance(content, dict):
        return {"parseable": False}

    allowed_fields = (
        "company_id",
        "price",
        "currency",
        "quoted_at",
        "data_mode",
        "source",
        "note",
    )
    return {
        field: content[field]
        for field in allowed_fields
        if field in content
    }


async def main() -> int:
    config = get_llm_config(BACKEND / ".env")
    if config is None or config.provider != "deepseek":
        print("配置错误：DeepSeek 配置不完整。")
        return 1

    model = ChatDeepSeek(
        model=config.model,
        api_key=config.api_key,
        temperature=0,
        timeout=30,
        max_retries=0,
        max_tokens=500,
        extra_body={"thinking": {"type": "disabled"}},
    )
    agent = build_langchain_agent(model)
    request = ResearchRequest(
        company_id="NVDA",
        question=(
            "请必须调用 get_quote 工具查询 NVDA 的教学模拟报价，"
            "然后明确说明数据性质。"
        ),
        data_mode="fixture",
        as_of="2026-09-15T16:00:00+08:00",
    )

    try:
        async with asyncio.timeout(60):
            result = await invoke_langchain_agent(agent, request)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print(f"运行失败：{type(error).__name__}")
        return 1

    trace: list[dict[str, object]] = []
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    tool_result: dict[str, object] | None = None
    final_answer = ""

    for message in result.get("messages", []):
        if isinstance(message, HumanMessage):
            trace.append({"type": "HumanMessage"})
        elif isinstance(message, AIMessage):
            for field in usage:
                value = (message.usage_metadata or {}).get(field)
                if isinstance(value, int):
                    usage[field] += value

            if message.tool_calls:
                trace.append(
                    {
                        "type": "AIMessage(tool_calls)",
                        "tools": [
                            call.get("name") for call in message.tool_calls
                        ],
                        "arguments": [
                            {
                                "company_id": call.get("args", {}).get(
                                    "company_id"
                                )
                            }
                            for call in message.tool_calls
                        ],
                    }
                )
            else:
                trace.append({"type": "AIMessage(final)"})
                final_answer = str(message.content)
        elif isinstance(message, ToolMessage):
            trace.append({"type": "ToolMessage", "tool": message.name})
            tool_result = safe_tool_result(message)
        else:
            trace.append({"type": type(message).__name__})

    expected_sequence = [
        "HumanMessage",
        "AIMessage(tool_calls)",
        "ToolMessage",
        "AIMessage(final)",
    ]
    fixture_ok = bool(
        tool_result
        and tool_result.get("company_id") == "NVDA"
        and tool_result.get("price") == 100.0
        and tool_result.get("data_mode") == "fixture"
        and tool_result.get("source") == "本地教学模拟数据"
    )
    final_ok = (
        "100" in final_answer
        and ("教学" in final_answer or "模拟" in final_answer)
        and ("不是实时" in final_answer or "非实时" in final_answer)
    )
    passed = (
        [item["type"] for item in trace] == expected_sequence
        and fixture_ok
        and final_ok
    )

    print(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "model": config.model,
                "temperature": 0,
                "timeout_seconds": 30,
                "max_retries": 0,
                "authorized_tools": [tool.name for tool in build_langchain_tools()],
                "trace": trace,
                "tool_result": tool_result,
                "final_answer": final_answer,
                "usage": usage,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


raise SystemExit(asyncio.run(main()))
PY
