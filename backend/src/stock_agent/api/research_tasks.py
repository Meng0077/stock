import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any


class ResearchTaskAlreadyRunningError(RuntimeError):
    pass


@dataclass
class RunningResearchTask:
    task: asyncio.Task[None]

    # 只有通过我们自己的 cancel API
    # 主动取消时才设置为 True。
    cancel_requested: bool = False


_RUNNING_RESEARCH_TASKS: dict[str, RunningResearchTask] = {}


def is_research_task_running(thread_id: str) -> bool:
    running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
    return running_task is not None and not running_task.task.done()


def _cleanup_research_task(
    thread_id: str,
    completed_task: asyncio.Task[None],
) -> None:
    current_running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
    if current_running_task is not None and current_running_task.task is completed_task:
        _RUNNING_RESEARCH_TASKS.pop(thread_id, None)


def start_research_task(
    thread_id: str,
    operation: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    """
    启动一个后台 Research Workflow。

    调用后立即返回，不等待 Workflow 完成；
    Task Registry 持有 Task，供重复执行检查和取消使用。
    """
    if is_research_task_running(thread_id):
        raise ResearchTaskAlreadyRunningError(
            f"research workflow {thread_id} is already running"
        )

    task = asyncio.create_task(operation())
    _RUNNING_RESEARCH_TASKS[thread_id] = RunningResearchTask(task=task)
    task.add_done_callback(
        lambda completed_task: _cleanup_research_task(thread_id, completed_task)
    )


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


def is_research_cancel_requested(thread_id: str) -> bool:
    running_task = _RUNNING_RESEARCH_TASKS.get(thread_id)
    return running_task is not None and running_task.cancel_requested
