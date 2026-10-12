"""Day39: SSE cursor, wire format, replay, and terminal behavior."""

import asyncio
from datetime import datetime, timezone
from typing import cast

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from stock_agent.api.app import create_app
from stock_agent.api.dependencies import get_research_event_store
from stock_agent.api.research_event_store import ResearchEventStore
from stock_agent.api.research_sse import (
    encode_sse_event,
    resolve_last_event_id,
    stream_research_events,
)
from stock_agent.schemas.research_events import ResearchEvent, ResearchEventType


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def make_event(
    event_id: int,
    event_type: ResearchEventType,
    data: dict,
) -> ResearchEvent:
    return ResearchEvent(
        event_id=event_id,
        thread_id="thread-a",
        type=event_type,
        data=data,
        created_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )


def test_query_cursor_takes_precedence_over_header() -> None:
    assert resolve_last_event_id(
        query_last_event_id=3,
        header_last_event_id="2",
    ) == 3


@pytest.mark.parametrize("value", ["invalid", "-1"])
def test_invalid_last_event_id_header_returns_400(value: str) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_last_event_id(
            query_last_event_id=None,
            header_last_event_id=value,
        )

    assert error.value.status_code == 400


def test_encode_sse_event_contains_id_type_and_json_payload() -> None:
    frame = encode_sse_event(
        make_event(7, "answer_delta", {"text": "NVDA"})
    )

    assert frame.startswith("id: 7\nevent: answer_delta\ndata: ")
    assert '"thread_id":"thread-a"' in frame
    assert '"text":"NVDA"' in frame
    assert frame.endswith("\n\n")


def test_replayed_terminal_event_closes_stream_and_unsubscribes() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        completed = await store.publish(
            "thread-a",
            "completed",
            {"result": "done"},
        )
        queue, replay, _, latest_is_terminal = await store.subscribe("thread-a")

        frames = [
            frame
            async for frame in stream_research_events(
                request=cast(Request, ConnectedRequest()),
                thread_id="thread-a",
                queue=queue,
                replay_events=replay,
                latest_is_terminal=latest_is_terminal,
                event_store=store,
            )
        ]

        assert frames == [encode_sse_event(completed)]
        assert "thread-a" not in store._subscribers

    asyncio.run(scenario())


def test_live_terminal_event_closes_stream() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        queue, replay, _, latest_is_terminal = await store.subscribe("thread-a")
        completed = await store.publish(
            "thread-a",
            "completed",
            {"result": "done"},
        )

        frames = [
            frame
            async for frame in stream_research_events(
                request=cast(Request, ConnectedRequest()),
                thread_id="thread-a",
                queue=queue,
                replay_events=replay,
                latest_is_terminal=latest_is_terminal,
                event_store=store,
            )
        ]

        assert frames == [encode_sse_event(completed)]

    asyncio.run(scenario())


def test_closed_subscriber_sentinel_ends_stream() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        queue, replay, _, latest_is_terminal = await store.subscribe("thread-a")
        queue.put_nowait(None)

        frames = [
            frame
            async for frame in stream_research_events(
                request=cast(Request, ConnectedRequest()),
                thread_id="thread-a",
                queue=queue,
                replay_events=replay,
                latest_is_terminal=latest_is_terminal,
                event_store=store,
            )
        ]

        assert frames == []
        assert "thread-a" not in store._subscribers

    asyncio.run(scenario())


def test_events_endpoint_replays_terminal_event_as_sse() -> None:
    store = ResearchEventStore()
    completed = asyncio.run(
        store.publish("thread-a", "completed", {"result": "done"})
    )
    application = create_app()
    application.dependency_overrides[get_research_event_store] = lambda: store

    with TestClient(application) as client:
        response = client.get("/api/research/thread-a/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == encode_sse_event(completed)


def test_events_endpoint_rejects_cursor_older_than_replay_window() -> None:
    store = ResearchEventStore(max_events_per_thread=2)

    async def publish_events() -> None:
        for _ in range(3):
            await store.publish("thread-a", "stage_changed")

    asyncio.run(publish_events())
    application = create_app()
    application.dependency_overrides[get_research_event_store] = lambda: store

    with TestClient(application) as client:
        response = client.get(
            "/api/research/thread-a/events",
            params={"last_event_id": 0},
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Research event history is no longer available"
    }


def test_events_endpoint_closes_when_cursor_is_latest_terminal() -> None:
    store = ResearchEventStore()
    completed = asyncio.run(
        store.publish("thread-a", "completed", {"result": "done"})
    )
    application = create_app()
    application.dependency_overrides[get_research_event_store] = lambda: store

    with TestClient(application) as client:
        response = client.get(
            "/api/research/thread-a/events",
            headers={"Last-Event-ID": str(completed.event_id)},
        )

    assert response.status_code == 200
    assert response.text == ""
