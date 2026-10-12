import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from stock_agent.api.dependencies import get_research_event_store
from stock_agent.api.research_event_store import (
    ResearchEventStore,
    SubscriberQueue,
    TERMINAL_EVENT_TYPES,
)
from stock_agent.schemas.research_events import ResearchEvent


def resolve_last_event_id(
    *,
    query_last_event_id: int | None,
    header_last_event_id: str | None,
) -> int | None:
    if query_last_event_id is not None:
        return query_last_event_id
    if header_last_event_id is not None:
        try:
            value = int(header_last_event_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID")
        if value < 0:
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID")
        return value
    return None


def encode_sse_event(event: ResearchEvent) -> str:
    """ResearchEvent 编码成 SSE"""

    return (
        f"id: {event.event_id}\n"
        f"event: {event.type}\n"
        f"data: {event.model_dump_json()}\n"
        "\n"
    )


HEARTBEAT_SECONDS = 15

HEARTBEAT_FRAME = ": heartbeat\n\n"

router = APIRouter()


async def stream_research_events(
    *,
    request: Request,
    thread_id: str,
    queue: SubscriberQueue,
    replay_events: list[ResearchEvent],
    latest_is_terminal: bool,
    event_store: ResearchEventStore,
):
    try:
        for event in replay_events:
            yield encode_sse_event(event)

        # replay 全部发完，再判断 thread 的最新事件是不是 terminal。
        if latest_is_terminal:
            return

        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield HEARTBEAT_FRAME
                continue

            if event is None:
                return

            yield encode_sse_event(event)
            if event.type in TERMINAL_EVENT_TYPES:
                return
    finally:
        # 如果循环退出，确保取消订阅
        await event_store.unsubscribe(thread_id=thread_id, queue=queue)


@router.get("/api/research/{thread_id}/events")
async def research_events(
    thread_id: str,
    request: Request,
    last_event_id: int | None = Query(default=None, ge=0),
    event_store: ResearchEventStore = Depends(get_research_event_store),
):
    cursor = resolve_last_event_id(
        query_last_event_id=last_event_id,
        header_last_event_id=request.headers.get("last-event-id"),
    )

    # subscribe to the event store
    queue, replay_events, replay_complete, latest_is_terminal = await event_store.subscribe(
        thread_id=thread_id,
        last_event_id=cursor,
    )

    if not replay_complete:
        await event_store.unsubscribe(thread_id=thread_id, queue=queue)
        raise HTTPException(
            status_code=409,
            detail="Research event history is no longer available",
        )

    return StreamingResponse(
        stream_research_events(
            request=request,
            thread_id=thread_id,
            queue=queue,
            replay_events=replay_events,
            latest_is_terminal=latest_is_terminal,
            event_store=event_store,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
