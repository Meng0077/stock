"""进程内 Research Task Registry 的离线验收。"""

import asyncio
from typing import TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from stock_agent.api.research_tasks import (
    ResearchTaskAlreadyRunningError,
    ResearchTaskCancelledError,
    cancel_research_task,
    is_research_task_running,
    run_research_task,
)


def test_completed_task_is_removed_from_registry() -> None:
    async def scenario() -> None:
        async def operation() -> dict[str, object]:
            return {"output": "completed"}

        result = await run_research_task("thread-completed", operation)

        assert result == {"output": "completed"}
        assert not is_research_task_running("thread-completed")
        assert not cancel_research_task("thread-completed")

    asyncio.run(scenario())


def test_same_thread_cannot_run_twice_concurrently() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> dict[str, object]:
            started.set()
            await release.wait()
            return {"output": "completed"}

        async def duplicate_operation() -> dict[str, object]:
            raise AssertionError("duplicate operation must not start")

        first_task = asyncio.create_task(
            run_research_task("thread-duplicate", operation)
        )
        await started.wait()

        assert is_research_task_running("thread-duplicate")
        with pytest.raises(ResearchTaskAlreadyRunningError):
            await run_research_task(
                "thread-duplicate",
                duplicate_operation,
            )

        release.set()
        assert await first_task == {"output": "completed"}
        assert not is_research_task_running("thread-duplicate")

    asyncio.run(scenario())


def test_cancel_request_is_reported_and_registry_is_cleaned() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def operation() -> dict[str, object]:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return {}

        task = asyncio.create_task(
            run_research_task("thread-cancel", operation)
        )
        await started.wait()

        assert cancel_research_task("thread-cancel")
        with pytest.raises(ResearchTaskCancelledError):
            await task

        assert cancelled.is_set()
        assert not is_research_task_running("thread-cancel")
        assert not cancel_research_task("thread-cancel")

    asyncio.run(scenario())


def test_external_cancellation_is_not_converted_to_api_cancellation() -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        async def operation() -> dict[str, object]:
            started.set()
            await asyncio.Event().wait()
            return {}

        task = asyncio.create_task(
            run_research_task("thread-external-cancel", operation)
        )
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert not is_research_task_running("thread-external-cancel")

    asyncio.run(scenario())


def test_cancelled_langgraph_can_continue_from_checkpoint() -> None:
    class WorkflowState(TypedDict):
        status: str

    async def scenario() -> None:
        started = asyncio.Event()
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

        first_run = asyncio.create_task(
            run_research_task(
                thread_id,
                lambda: graph.ainvoke(
                    {"status": "started"},
                    config=config,
                ),
            )
        )
        await started.wait()

        assert cancel_research_task(thread_id)
        with pytest.raises(ResearchTaskCancelledError):
            await first_run

        cancelled_snapshot = await graph.aget_state(config)
        assert cancelled_snapshot.next == ("work",)

        result = await run_research_task(
            thread_id,
            lambda: graph.ainvoke(None, config=config),
        )

        assert result["status"] == "completed"
        completed_snapshot = await graph.aget_state(config)
        assert completed_snapshot.next == ()
        assert attempts == 2

    asyncio.run(scenario())
