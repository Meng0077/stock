"""Day39: LangGraph stream chunks are translated into Research events."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from stock_agent.agents.context import ResearchContext
from stock_agent.api.research_event_store import ResearchEventStore
from stock_agent.api.research_stream_runner import (
    build_target_resolution_event_data,
    get_answer_delta,
    get_task_stage,
    run_research_stream,
)
from stock_agent.company.resolver import TargetResolution


class Message:
    def __init__(self, content: object) -> None:
        self.content = content


class CompletedGraph:
    async def astream(self, graph_input, **kwargs):
        yield "tasks", {"name": "resolve_target", "input": {}}
        yield "updates", {
            "resolve_target": {
                "target_resolution": TargetResolution(
                    resolved_targets=["NVDA", "AAPL"]
                )
            }
        }
        yield "messages", (
            Message("两家公司研究完成"),
            {"langgraph_node": "answer"},
        )

    async def aget_state(self, config):
        return SimpleNamespace(
            interrupts=(),
            values={"output": "两家公司研究完成"},
        )


class InterruptedGraph:
    async def astream(self, graph_input, **kwargs):
        if False:
            yield None

    async def aget_state(self, config):
        return SimpleNamespace(
            interrupts=(
                SimpleNamespace(
                    value={
                        "type": "target_clarification",
                        "message": "请补充 ticker",
                    }
                ),
            ),
            values={},
        )


def test_task_stage_only_uses_started_known_nodes() -> None:
    assert get_task_stage({"name": "planner", "input": {}}) == "planning"
    assert get_task_stage({"name": "planner"}) is None
    assert get_task_stage({"name": "unknown", "input": {}}) is None


def test_answer_delta_only_uses_answer_node_text() -> None:
    assert get_answer_delta(
        (Message("N"), {"langgraph_node": "answer"})
    ) == "N"
    assert get_answer_delta(
        (Message("N"), {"langgraph_node": "planner"})
    ) is None
    assert get_answer_delta((Message({}), {"langgraph_node": "answer"})) is None
    assert get_answer_delta((Message("N"),)) is None
    assert get_answer_delta((Message("N"), {}, "extra")) is None


def test_target_resolution_event_uses_plural_company_ids() -> None:
    data = build_target_resolution_event_data(
        {
            "target_resolution": TargetResolution(
                resolved_targets=["NVDA", "AAPL"]
            )
        }
    )

    assert data["company_ids"] == ["NVDA", "AAPL"]
    assert "company_id" not in data


def test_completed_graph_emits_structured_events_in_order() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        snapshot = await run_research_stream(
            graph=CompletedGraph(),
            graph_input={"request": "example"},
            thread_id="thread-a",
            execution="start",
            context=ResearchContext(
                as_of=datetime(2026, 10, 12, tzinfo=timezone.utc)
            ),
            config={"configurable": {"thread_id": "thread-a"}},
            event_store=store,
        )

        queue, events, complete = await store.subscribe("thread-a")
        assert complete is True
        assert [event.type for event in events] == [
            "workflow_started",
            "stage_changed",
            "target_resolution",
            "answer_delta",
            "completed",
        ]
        assert events[1].data == {"stage": "target_resolution"}
        assert events[2].data["status"] == "resolved"
        assert events[2].data["company_ids"] == ["NVDA", "AAPL"]
        assert events[3].data == {"text": "两家公司研究完成"}
        assert snapshot.values["output"] == "两家公司研究完成"
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())


def test_interrupted_graph_emits_needs_input_without_completed() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        await run_research_stream(
            graph=InterruptedGraph(),
            graph_input={},
            thread_id="thread-a",
            execution="start",
            context=ResearchContext(
                as_of=datetime(2026, 10, 12, tzinfo=timezone.utc)
            ),
            config={"configurable": {"thread_id": "thread-a"}},
            event_store=store,
        )

        queue, events, _ = await store.subscribe("thread-a")
        assert [event.type for event in events] == [
            "workflow_started",
            "needs_input",
        ]
        assert events[-1].data["type"] == "target_clarification"
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())
