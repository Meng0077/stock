"""D04 离线超时与取消练习，详见 docs/day04/05_timeouts.md、07_cancellation.md。

Task 5：离线演示单工具超时与一次任务共用的总时限。

Task 7 后续：create_task -> cancel -> await；在 finally 记录清理，
确认取消后无新调用。最终用 asyncio.run(main()) 启动，不使用密钥或网络。
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

Tool = Callable[[Callable[[], None]], Awaitable[None]]

SLOW_TIME = 5
FAST_TIME = 1
TOOL_TIMEOUT = 3
TASK_TIMEOUT = 10


async def slow(fn: Callable[[], None]) -> None:
    await asyncio.sleep(SLOW_TIME)
    fn()


async def fast(fn: Callable[[], None]) -> None:
    await asyncio.sleep(FAST_TIME)
    fn()


async def completion_demo() -> list[str]:
    """只有工具完成等待并执行回调，才写入完成记录。"""
    completed: list[str] = []
    await fast(lambda: completed.append("fast"))
    await slow(lambda: completed.append("slow"))
    return completed


async def run_tool(
    name: str,
    tool: Tool,
    completed: list[str],
    *,
    timeout_seconds: float,
) -> dict[str, str | bool]:
    """仅将本次工具等待触发的超时转换为工具结果。"""
    try:
        async with asyncio.timeout(timeout_seconds) as local_limit:
            await tool(lambda: completed.append(name))
    except TimeoutError:
        if not local_limit.expired():
            raise
        return {"tool": name, "ok": False, "error": "tool_timeout"}
    return {"tool": name, "ok": True}


async def timeout_demo(
    *,
    tool_timeout: float = TOOL_TIMEOUT,
    task_timeout: float = TASK_TIMEOUT,
    steps: Sequence[tuple[str, Tool]] | None = None,
) -> dict[str, object]:
    """所有步骤共用一个总时限；总超时后不再启动后续步骤。"""
    if steps is None:
        steps = (("fast", fast), ("slow", slow), ("after", fast))

    started: list[str] = []
    completed: list[str] = []
    results: list[dict[str, str | bool]] = []
    try:
        async with asyncio.timeout(task_timeout) as total_limit:
            for name, tool in steps:
                if total_limit.expired():
                    raise TimeoutError
                started.append(name)
                result = await run_tool(
                    name, tool, completed, timeout_seconds=tool_timeout
                )
                if total_limit.expired():
                    raise TimeoutError
                results.append(result)
    except TimeoutError:
        if not total_limit.expired():
            raise
        status = "task_timeout"
    else:
        status = "completed"
    return {
        "status": status,
        "started": started,
        "completed": completed,
        "results": results,
    }


if __name__ == "__main__":
    print(asyncio.run(timeout_demo()))
