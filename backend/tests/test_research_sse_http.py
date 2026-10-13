"""Day39: 通过真实 FastAPI HTTP 路由验证 Research SSE 主链路。"""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import httpx
from langgraph.types import Command

from stock_agent.api import dependencies
from stock_agent.api.app import create_app
from stock_agent.api.research_event_store import ResearchEventStore
from stock_agent.api import research_sse


THREAD_ID = "12345678-1234-5678-1234-567812345678"
QUESTION = "现在股价多少"
CLARIFICATION = {
    "reason": "missing_target",
    "prompt": "请补充要查询的证券。",
}


def parse_sse_events(body: str) -> list[dict]:
    events = []
    for frame in body.split("\n\n"):
        if not frame or frame.startswith(":"):
            continue
        lines = frame.splitlines()
        events.append({
            "id": int(lines[0].removeprefix("id: ")),
            "type": lines[1].removeprefix("event: "),
            "data": json.loads(lines[2].removeprefix("data: ")),
        })
    return events


async def wait_for_subscriber(store: ResearchEventStore, thread_id: str) -> None:
    for _ in range(100):
        if store._subscribers.get(thread_id):
            return
        await asyncio.sleep(0)
    raise AssertionError("SSE subscriber was not connected")


async def wait_for_event(
    store: ResearchEventStore,
    thread_id: str,
    event_type: str,
) -> None:
    for _ in range(100):
        if any(
            event.type == event_type
            for event in store._buffers.get(thread_id, ())
        ):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"event {event_type} was not published")


def build_http_client(graph, store: ResearchEventStore) -> httpx.AsyncClient:
    application = create_app()
    application.dependency_overrides[dependencies.get_research_graph] = lambda: graph
    application.dependency_overrides[dependencies.get_research_event_store] = lambda: store
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    )


class ClarificationGraph:
    def __init__(self):
        self.phase = "new"
        self.request = None
        self.output = "NVDA 当前研究结果"

    async def astream(self, graph_input, **kwargs):
        if isinstance(graph_input, Command):
            assert self.request.question == QUESTION
            self.request = self.request.model_copy(update={"company_ids": [graph_input.resume]})
            self.phase = "completed"
            yield "messages", (
                SimpleNamespace(content=self.output),
                {"langgraph_node": "answer"},
            )
            return

        self.request = graph_input["request"]
        self.phase = "needs_input"
        if False:
            yield None

    async def aget_state(self, config):
        if self.phase == "new":
            return SimpleNamespace(values={}, next=(), interrupts=())
        if self.phase == "needs_input":
            return SimpleNamespace(
                values={"request": self.request},
                next=("resolve_target",),
                interrupts=(SimpleNamespace(value=CLARIFICATION),),
            )
        return SimpleNamespace(
            values={"request": self.request, "output": self.output},
            next=(),
            interrupts=(),
        )


class BlockingGraph:
    def __init__(self):
        self.started = asyncio.Event()

    async def astream(self, graph_input, **kwargs):
        self.started.set()
        await asyncio.Event().wait()
        if False:
            yield None

    async def aget_state(self, config):
        return SimpleNamespace(values={}, next=(), interrupts=())


class CompletedGraph:
    output = "NVDA 研究完成"

    async def astream(self, graph_input, **kwargs):
        yield "messages", (
            SimpleNamespace(content=self.output),
            {"langgraph_node": "answer"},
        )

    async def aget_state(self, config):
        return SimpleNamespace(
            values={"output": self.output},
            next=(),
            interrupts=(),
        )


def test_http_start_returns_generated_thread_and_replays_completed_event() -> None:
    async def scenario() -> None:
        graph = CompletedGraph()
        store = ResearchEventStore()

        async with build_http_client(graph, store) as client:
            start_response = await client.post(
                "/api/research",
                json={"message": "NVDA 怎么看"},
            )
            thread_id = start_response.json()["thread_id"]
            await wait_for_event(store, thread_id, "completed")
            stream_response = await client.get(
                f"/api/research/{thread_id}/events"
            )

        assert start_response.json() == {
            "thread_id": thread_id,
            "status": "accepted",
        }
        UUID(thread_id)
        events = parse_sse_events(stream_response.text)
        assert [event["type"] for event in events] == [
            "workflow_started",
            "answer_delta",
            "completed",
        ]
        assert events[-1]["data"]["data"] == {"result": graph.output}

    asyncio.run(scenario())


def test_http_sse_keeps_connection_through_needs_input_and_resume(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(research_sse, "HEARTBEAT_SECONDS", 0.01)
        graph = ClarificationGraph()
        store = ResearchEventStore()

        async with build_http_client(graph, store) as client:
            start_response = await client.post(
                "/api/research",
                json={"message": QUESTION},
            )
            thread_id = start_response.json()["thread_id"]
            assert start_response.json()["status"] == "accepted"

            stream_task = asyncio.create_task(
                client.get(f"/api/research/{thread_id}/events")
            )
            await wait_for_subscriber(store, thread_id)
            await wait_for_event(store, thread_id, "needs_input")

            await asyncio.sleep(0.03)
            assert not stream_task.done()

            resume_response = await client.post(
                "/api/research/resume",
                json={"thread_id": thread_id, "answer": "NVDA"},
            )
            stream_response = await asyncio.wait_for(stream_task, timeout=1)

        assert resume_response.json() == {
            "thread_id": thread_id,
            "status": "accepted",
        }
        assert graph.request.question == QUESTION
        assert graph.request.company_ids == ["NVDA"]
        assert ": heartbeat\n\n" in stream_response.text

        events = parse_sse_events(stream_response.text)
        assert [event["id"] for event in events] == [1, 2, 3, 4, 5]
        assert [event["type"] for event in events] == [
            "workflow_started",
            "needs_input",
            "workflow_started",
            "answer_delta",
            "completed",
        ]
        assert events[0]["data"]["data"] == {"execution": "start"}
        assert events[2]["data"]["data"] == {"execution": "resume"}
        assert events[-1]["data"]["data"]["result"] == graph.output

    asyncio.run(scenario())


def test_http_sse_last_event_id_replays_only_missing_events() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        await store.publish(THREAD_ID, "workflow_started", {"execution": "start"})
        await store.publish(THREAD_ID, "answer_delta", {"text": "NVDA"})
        await store.publish(THREAD_ID, "completed", {"result": "done"})

        async with build_http_client(object(), store) as client:
            response = await client.get(
                f"/api/research/{THREAD_ID}/events",
                headers={"Last-Event-ID": "1"},
            )

        assert response.status_code == 200
        events = parse_sse_events(response.text)
        assert [event["id"] for event in events] == [2, 3]
        assert [event["type"] for event in events] == ["answer_delta", "completed"]

    asyncio.run(scenario())


def test_http_cancel_publishes_only_cancelled_terminal_event() -> None:
    async def scenario() -> None:
        graph = BlockingGraph()
        store = ResearchEventStore()

        async with build_http_client(graph, store) as client:
            research_response = await client.post(
                "/api/research",
                json={"message": "NVDA 怎么看"},
            )
            thread_id = research_response.json()["thread_id"]
            await asyncio.wait_for(graph.started.wait(), timeout=1)

            stream_task = asyncio.create_task(
                client.get(f"/api/research/{thread_id}/events")
            )
            await wait_for_subscriber(store, thread_id)
            cancel_response = await client.post(f"/api/research/{thread_id}/cancel")
            stream_response = await asyncio.wait_for(stream_task, timeout=1)

        assert cancel_response.json() == {
            "thread_id": thread_id,
            "status": "cancelling",
        }
        assert research_response.json()["status"] == "accepted"
        events = parse_sse_events(stream_response.text)
        assert [event["type"] for event in events] == [
            "workflow_started",
            "cancelled",
        ]

    asyncio.run(scenario())


def test_http_sse_rejects_expired_terminal_cursor() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(terminal_ttl_seconds=0)
        await store.publish(THREAD_ID, "completed", {"result": "done"})

        async with build_http_client(object(), store) as client:
            response = await client.get(
                f"/api/research/{THREAD_ID}/events",
                headers={"Last-Event-ID": "1"},
            )

        assert response.status_code == 409
        assert response.json() == {
            "detail": "Research event history is no longer available"
        }

    asyncio.run(scenario())
