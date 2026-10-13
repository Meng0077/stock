"""进程内 Research Task Registry 的离线验收。"""

import asyncio
from typing import TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from stock_agent.api.research_tasks import (
    ResearchTaskAlreadyRunningError,
    cancel_research_task,
    is_research_cancel_requested,
    is_research_task_running,
    start_research_task,
)


async def wait_until_stopped(thread_id: str) -> None:
    for _ in range(100):
        if not is_research_task_running(thread_id):
            await asyncio.sleep(0)
            return
        await asyncio.sleep(0)
    raise AssertionError(f"research workflow {thread_id} did not stop")


def test_completed_task_is_removed_from_registry() -> None:
    async def scenario() -> None:
        completed = asyncio.Event()

        async def operation() -> None:
            completed.set()

        start_research_task("thread-completed", operation)
        await completed.wait()
        await wait_until_stopped("thread-completed")

        assert not is_research_task_running("thread-completed")
        assert not cancel_research_task("thread-completed")

    asyncio.run(scenario())


def test_same_thread_cannot_run_twice_concurrently() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> None:
            started.set()
            await release.wait()

        async def duplicate_operation() -> None:
            raise AssertionError("duplicate operation must not start")

        start_research_task("thread-duplicate", operation)
        await started.wait()

        assert is_research_task_running("thread-duplicate")
        with pytest.raises(ResearchTaskAlreadyRunningError):
            start_research_task("thread-duplicate", duplicate_operation)

        release.set()
        await wait_until_stopped("thread-duplicate")

    asyncio.run(scenario())


def test_different_threads_can_run_concurrently() -> None:
    async def scenario() -> None:
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release = asyncio.Event()

        async def first_operation() -> None:
            first_started.set()
            await release.wait()

        async def second_operation() -> None:
            second_started.set()
            await release.wait()

        start_research_task("thread-first", first_operation)
        start_research_task("thread-second", second_operation)
        await first_started.wait()
        await second_started.wait()

        assert is_research_task_running("thread-first")
        assert is_research_task_running("thread-second")

        release.set()
        await wait_until_stopped("thread-first")
        await wait_until_stopped("thread-second")

    asyncio.run(scenario())


def test_cancel_request_is_reported_and_registry_is_cleaned() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def operation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        start_research_task("thread-cancel", operation)
        await started.wait()

        assert cancel_research_task("thread-cancel")
        assert is_research_cancel_requested("thread-cancel")
        await cancelled.wait()
        await wait_until_stopped("thread-cancel")

        assert not is_research_cancel_requested("thread-cancel")
        assert not cancel_research_task("thread-cancel")

    asyncio.run(scenario())


def test_cancelled_langgraph_can_continue_from_checkpoint() -> None:
    class WorkflowState(TypedDict):
        status: str

    async def scenario() -> None:
        started = asyncio.Event()
        completed = asyncio.Event()
        attempts = 0

        async def work_node(state: WorkflowState) -> dict[str, str]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                started.set()
                await asyncio.Event().wait()
            return {"status": "completed"}

        builder = StateGraph(WorkflowState)
        builder.add_node("work", work_node)
        builder.add_edge(START, "work")
        builder.add_edge("work", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        thread_id = "thread-checkpoint-continue"
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id}
        }

        async def start_operation() -> None:
            await graph.ainvoke({"status": "started"}, config=config)

        start_research_task(thread_id, start_operation)
        await started.wait()

        assert cancel_research_task(thread_id)
        await wait_until_stopped(thread_id)

        cancelled_snapshot = await graph.aget_state(config)
        assert cancelled_snapshot.next == ("work",)

        async def continue_operation() -> None:
            await graph.ainvoke(None, config=config)
            completed.set()

        start_research_task(thread_id, continue_operation)
        await completed.wait()
        await wait_until_stopped(thread_id)

        completed_snapshot = await graph.aget_state(config)
        assert completed_snapshot.next == ()
        assert completed_snapshot.values["status"] == "completed"
        assert attempts == 2

    asyncio.run(scenario())
