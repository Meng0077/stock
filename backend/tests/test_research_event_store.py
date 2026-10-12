"""Day39: process-local Research event buffer and replay tests."""

import asyncio

from stock_agent.api.research_event_store import ResearchEventStore


def test_publish_assigns_monotonic_ids_per_thread() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()

        first = await store.publish("thread-a", "workflow_started")
        second = await store.publish("thread-a", "stage_changed")
        other = await store.publish("thread-b", "workflow_started")

        assert [first.event_id, second.event_id] == [1, 2]
        assert other.event_id == 1
        assert first.thread_id == "thread-a"

    asyncio.run(scenario())


def test_subscribe_replays_events_after_cursor_and_receives_live_events() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        await store.publish("thread-a", "workflow_started")
        await store.publish("thread-a", "stage_changed", {"stage": "planning"})

        queue, replay, replay_complete = await store.subscribe(
            "thread-a",
            last_event_id=1,
        )
        assert replay_complete is True
        assert [event.event_id for event in replay] == [2]

        published = await store.publish(
            "thread-a",
            "answer_delta",
            {"text": "N"},
        )
        assert await queue.get() == published

        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())


def test_subscribe_reports_cursor_older_than_retained_buffer() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(max_events_per_thread=2)
        for _ in range(3):
            await store.publish("thread-a", "stage_changed")

        queue, replay, replay_complete = await store.subscribe(
            "thread-a",
            last_event_id=0,
        )

        assert replay_complete is False
        assert [event.event_id for event in replay] == [2, 3]
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())


def test_subscribe_without_cursor_replays_current_buffer() -> None:
    async def scenario() -> None:
        store = ResearchEventStore()
        await store.publish("thread-a", "workflow_started")
        await store.publish("thread-a", "completed", {"result": "done"})

        queue, replay, replay_complete = await store.subscribe("thread-a")

        assert replay_complete is True
        assert [event.type for event in replay] == [
            "workflow_started",
            "completed",
        ]
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())


def test_slow_subscriber_is_closed_without_blocking_publisher() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(subscriber_queue_size=1)
        queue, _, _ = await store.subscribe("thread-a")

        await store.publish("thread-a", "workflow_started")
        second = await asyncio.wait_for(
            store.publish("thread-a", "answer_delta", {"text": "N"}),
            timeout=0.1,
        )

        assert second.event_id == 2
        assert await queue.get() is None
        assert "thread-a" not in store._subscribers

    asyncio.run(scenario())


def test_publish_continues_after_subscriber_overflow() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(subscriber_queue_size=1)
        queue, _, _ = await store.subscribe("thread-a")

        await store.publish("thread-a", "workflow_started")
        await store.publish("thread-a", "answer_delta", {"text": "N"})
        third = await store.publish("thread-a", "completed", {"result": "done"})

        assert await queue.get() is None
        assert third.event_id == 3

        replay_queue, replay, replay_complete = await store.subscribe(
            "thread-a",
            last_event_id=0,
        )
        assert replay_complete is True
        assert [event.event_id for event in replay] == [1, 2, 3]
        await store.unsubscribe("thread-a", replay_queue)

    asyncio.run(scenario())


def test_terminal_thread_remains_replayable_before_ttl() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(terminal_ttl_seconds=300)
        completed = await store.publish("thread-a", "completed", {"result": "done"})

        await store.cleanup_expired()
        queue, replay, replay_complete = await store.subscribe("thread-a", last_event_id=0)

        assert replay_complete is True
        assert replay == [completed]
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())


def test_cleanup_removes_expired_terminal_thread() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(terminal_ttl_seconds=0)
        await store.publish("thread-a", "completed", {"result": "done"})

        await store.cleanup_expired()

        assert "thread-a" not in store._buffers
        assert "thread-a" not in store._last_event_ids
        assert "thread-a" not in store._terminal_expires_at

        queue, replay, replay_complete = await store.subscribe("thread-a", last_event_id=1)
        assert replay == []
        assert replay_complete is False
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())


def test_non_terminal_event_cancels_terminal_expiration() -> None:
    async def scenario() -> None:
        store = ResearchEventStore(terminal_ttl_seconds=300)
        cancelled = await store.publish("thread-a", "cancelled")
        restarted = await store.publish("thread-a", "workflow_started")

        assert [cancelled.event_id, restarted.event_id] == [1, 2]
        assert "thread-a" not in store._terminal_expires_at

        await store.cleanup_expired()
        queue, replay, replay_complete = await store.subscribe("thread-a", last_event_id=0)
        assert replay_complete is True
        assert [event.event_id for event in replay] == [1, 2]
        await store.unsubscribe("thread-a", queue)

    asyncio.run(scenario())
