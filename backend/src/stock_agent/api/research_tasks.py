import asyncio
from collections.abc import (
    Callable,
    Coroutine,
)
from dataclasses import dataclass
from typing import Any


class ResearchTaskAlreadyRunningError(
    RuntimeError
):
    pass


class ResearchTaskCancelledError(
    RuntimeError
):
    pass


ResearchTaskResult = dict[str, Any]


@dataclass
class RunningResearchTask:
    task: asyncio.Task[
        ResearchTaskResult
    ]

    # 只有通过我们自己的 cancel API
    # 主动取消时才设置为 True。
    cancel_requested: bool = False


_RUNNING_RESEARCH_TASKS: dict[str, RunningResearchTask] = {}


def is_research_task_running(thread_id: str) -> bool:
    running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
    return running_task is not None and not running_task.task.done()


async def run_research_task(
    thread_id: str,
    operation: Callable[
        [],
        Coroutine[Any, Any, ResearchTaskResult],
    ],
) -> ResearchTaskResult:
    """
    保证同一个 thread_id 同时只有一个 active run。

    Task Registry 只跟踪当前进程中的运行状态；
    Graph State 和恢复点仍由 LangGraph Checkpointer 管理。
    """

    if is_research_task_running(thread_id):
        raise ResearchTaskAlreadyRunningError(
            f"research workflow {thread_id} is already running"
        )

    task = asyncio.create_task(operation())
    _RUNNING_RESEARCH_TASKS[thread_id] = RunningResearchTask(task=task)

    try:
        return await task
    except asyncio.CancelledError as error:
        running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
        if (
            running_task is not None
            and running_task.task is task
            and running_task.cancel_requested
        ):
            raise ResearchTaskCancelledError(
                f"research workflow {thread_id} was cancelled"
            ) from error
        raise
    finally:
        current_running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
        if current_running_task is not None and current_running_task.task is task:
            _RUNNING_RESEARCH_TASKS.pop(thread_id, None)


def cancel_research_task(thread_id: str) -> bool:
    """
    主动取消一个正在运行的 research workflow。

    取消请求会被传递给运行中的 asyncio.Task；
    但我们无法保证它会立即停止，因为它可能在等待 I/O 或其他阻塞操作。
    """
    running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
    if running_task is not None and not running_task.task.done():
        running_task.cancel_requested = True
        running_task.task.cancel()
        return True

    return False
