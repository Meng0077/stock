"""
Day39：检查 LangGraph astream 的实际事件结构。

目的：
- 查看 tasks stream 的 node 生命周期结构；
- 查看 updates stream 的 node state update 结构；
- 查看 messages stream 的 token / metadata 结构；
- 为后续 ResearchEvent Adapter 提供真实 contract。

运行：

PYTHONPATH=backend/src \
backend/.venv/bin/python \
backend/examples/inspect_langgraph_stream.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pprint import pprint
from typing import Any

from langchain_deepseek import ChatDeepSeek
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph.graph import (
    build_initial_state,
    build_research_graph,
)
from stock_agent.llm_client import get_llm_config
from stock_agent.macro.config_factory import (
    build_macro_snapshot_builder,
)
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)
from stock_agent.schemas.research import ResearchRequest


BACKEND = Path(__file__).resolve().parents[1]


def print_stream_event(
    *,
    index: int,
    mode: str,
    chunk: Any,
) -> None:
    """
    打印一条 LangGraph stream event。

    暂时不做业务转换，
    这里就是为了观察当前 LangGraph 版本
    实际返回的数据结构。
    """

    print()
    print("=" * 100)
    print(f"EVENT #{index} | STREAM MODE: {mode}")
    print("=" * 100)

    pprint(
        chunk,
        width=120,
        sort_dicts=False,
    )


async def main() -> int:
    # ---------------------------------------------------------
    # 1. 读取现有 DeepSeek 配置
    # ---------------------------------------------------------

    config = get_llm_config(BACKEND / ".env")

    if config is None or config.provider != "deepseek":
        print(
            "配置错误：请在 backend/.env "
            "配置 DeepSeek。",
            file=sys.stderr,
        )
        return 1

    timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))

    # ---------------------------------------------------------
    # 2. 创建真实模型
    # ---------------------------------------------------------

    model = ChatDeepSeek(
        model=config.model,
        api_key=SecretStr(config.api_key),
        temperature=0,
        timeout=timeout,
        max_retries=0,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )

    # ---------------------------------------------------------
    # 3. 编译真实 LangGraph
    #
    # 使用 InMemorySaver，
    # 和当前 Day38 / Day39 本地版本保持一致。
    # ---------------------------------------------------------

    graph = build_research_graph(
        model,
        checkpointer=InMemorySaver(),
    )

    # ---------------------------------------------------------
    # 4. 构建这次研究请求
    #
    # +1 minute 与现有 live smoke 一致，
    # 给 Provider received_at / 网络请求留一个窗口。
    # ---------------------------------------------------------

    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)

    request = ResearchRequest(
        company_ids=[],
        question="NVDA 当前走势怎么看",
        data_mode="live",
        as_of=as_of,
    )

    # ---------------------------------------------------------
    # 5. 构建真实运行 Context
    # ---------------------------------------------------------

    context = ResearchContext(
        as_of=as_of,
        market_provider_factory=build_longbridge_market_provider,
        macro_builder_factory=build_macro_snapshot_builder,
        market_state="unknown",
    )

    # ---------------------------------------------------------
    # 6. thread_id
    #
    # 这里只是调试脚本，
    # 使用固定 ID 更容易观察 checkpoint。
    # ---------------------------------------------------------

    graph_config = RunnableConfig(
        configurable={"thread_id": "day39-inspect-stream"}
    )

    initial_state = build_initial_state(request)

    print()
    print("#" * 100)
    print("LANGGRAPH STREAM INSPECTION")
    print("#" * 100)

    print()
    print("question:")
    print(request.question)

    print()
    print("thread_id:")
    print(graph_config["configurable"]["thread_id"])

    print()
    print("stream modes:")
    print(["tasks", "updates", "messages"])

    print()
    print("开始执行 Graph...")

    # ---------------------------------------------------------
    # 7. 核心：
    #    同时监听三个 stream mode
    #
    # tasks
    #     用于观察 node task 生命周期
    #
    # updates
    #     用于观察 node 完成后的 State update
    #
    # messages
    #     用于观察 LLM token / metadata
    # ---------------------------------------------------------

    event_index = 0

    try:
        async for mode, chunk in graph.astream(
            initial_state,
            context=context,
            config=graph_config,
            stream_mode=[
                "tasks",
                "updates",
                "messages",
            ],
        ):
            event_index += 1
            if event_index < 30:
                print_stream_event(
                    index=event_index,
                    mode=mode,
                    chunk=chunk,
                )

    except Exception as error:
        print()
        print("!" * 100)
        print("GRAPH STREAM FAILED")
        print("!" * 100)

        print(f"{type(error).__name__}: {error}")

        raise

    # ---------------------------------------------------------
    # 8. 查看最终 checkpoint
    #
    # 方便同时确认 stream 完成后，
    # Graph State 最终保存成什么样。
    # ---------------------------------------------------------

    snapshot = await graph.aget_state(graph_config)

    print()
    print("#" * 100)
    print("FINAL CHECKPOINT")
    print("#" * 100)

    print()
    print("next:")
    pprint(snapshot.next)

    print()
    print("interrupts:")
    pprint(snapshot.interrupts)

    print()
    print("state keys:")
    pprint(list(snapshot.values.keys()))

    print()
    print("#" * 100)
    print("LangGraph stream inspection completed.")
    print("#" * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
