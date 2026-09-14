"""D04 离线超时与取消练习，详见 docs/day04/05_timeouts.md、07_cancellation.md。

Task 5：离线演示单工具超时与一次任务共用的总时限。

Task 7：离线演示取消、等待终态和清理；不使用密钥或网络。
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
    except asyncio.CancelledError:
        raise
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


async def slow_work(started: asyncio.Event, events: list[str]) -> None:
    """通知调用者后等待；退出时记录 cleanup，并向外传播取消。"""
    try:
        events.append("started")
        started.set()
        await asyncio.sleep(SLOW_TIME)
        events.append("end")
    finally:
        events.append("cleanup")


async def cancellation_demo() -> dict[str, object]:
    """取消慢任务并等待清理；记录是否进入后续步骤。"""
    events: list[str] = []
    calls: list[str] = []
    started = asyncio.Event()
    task = asyncio.create_task(slow_work(started, events))
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        events.append("cancelled")
        status = "cancelled"
    else:
        calls.append("next_call")
        status = "completed"
    return {
        "status": status,
        "events": events,
        "calls": calls,
        "task_cancelled": task.cancelled(),
    }


async def main() -> None:
    """依次打印超时演示和取消演示的结果。"""
    print(await timeout_demo())
    task = asyncio.create_task(timeout_demo())

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print('------')
    print(await cancellation_demo())


if __name__ == "__main__":
    asyncio.run(main())
