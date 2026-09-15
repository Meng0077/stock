"""D07 Step 3：独立观察 LangChain tool loop 的最小加法实验。

本文件不接入股票工具，也不在模块导入阶段读取密钥、创建客户端或调用模型。
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain.tools import tool
from langchain_deepseek import ChatDeepSeek

from stock_agent.llm_client import get_llm_config


BACKEND = Path(__file__).resolve().parents[1]


@tool
def add(a: int, b: int) -> int:
    """计算两个整数的和。"""
    return a + b


def print_message_summary(result: dict[str, Any]) -> None:
    """只打印消息类型和工具名，不输出模型对象、密钥或完整内容。"""
    messages = result.get("messages", [])
    if not isinstance(messages, list):
        print("消息轨迹格式错误。")
        return

    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            print(f"{index}: HumanMessage")
        elif isinstance(message, AIMessage):
            if message.tool_calls:
                tool_names = [
                    call.get("name", "<unknown>") for call in message.tool_calls
                ]
                print(f"{index}: AIMessage tool_calls={tool_names}")
            else:
                print(f"{index}: AIMessage(final)")
        elif isinstance(message, ToolMessage):
            print(f"{index}: ToolMessage name={message.name}")
        else:
            print(f"{index}: {type(message).__name__}")


def smoke_result_is_valid(result: dict[str, Any]) -> bool:
    """检查 add 工具往返顺序和最终答案；合法时返回 True。"""
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        return False

    tool_call_index = next(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, AIMessage)
            and any(call.get("name") == "add" for call in message.tool_calls)
        ),
        None,
    )
    tool_result_index = next(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, ToolMessage) and message.name == "add"
        ),
        None,
    )
    final_index = len(messages) - 1
    final_message = messages[final_index]

    return (
        tool_call_index is not None
        and tool_result_index is not None
        and tool_call_index < tool_result_index < final_index
        and isinstance(final_message, AIMessage)
        and not final_message.tool_calls
        and "579" in str(final_message.content)
    )


def build_smoke_agent(model: Any) -> Any:
    """输入聊天模型；输出只注册 add 工具的 LangChain Agent。"""
    return create_agent(model=model, tools=[add])


async def run_smoke(agent: Any, question: str) -> dict[str, Any]:
    """输入 Agent 和问题；异步执行一次；输出含 messages 的 Agent state。"""
    if not question.strip():
        raise ValueError("question must not be empty")

    return await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": question,
                }
            ]
        }
    )


async def main() -> int:
    """读取 D07 实验配置并受控运行一次；成功返回 0，失败返回 1。"""
    config = get_llm_config(BACKEND / ".env")
    if config is None or config.provider != "deepseek":
        print("配置错误：请配置 DeepSeek 的模型名和 API Key。", file=sys.stderr)
        return 1

    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        print(
            "配置错误：MODEL_TIMEOUT_SECONDS 必须是大于 0 的有限数字。",
            file=sys.stderr,
        )
        return 1

    try:
        model = ChatDeepSeek(
            model=config.model,
            api_key=config.api_key,
            temperature=0,
            timeout=timeout,
            max_retries=0,
        )
        agent = build_smoke_agent(model)
        result = await run_smoke(
            agent=agent,
            question="必须使用 add 工具计算 123 + 456。",
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        print("LangChain 加法实验失败。", file=sys.stderr)
        return 1

    print_message_summary(result)
    if not smoke_result_is_valid(result):
        print("验收失败：未观察到 add 工具往返或最终答案不是 579。", file=sys.stderr)
        return 1

    print("验收通过：add 工具返回 579。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
