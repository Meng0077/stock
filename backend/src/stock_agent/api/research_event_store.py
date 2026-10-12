import asyncio
from collections import deque
from datetime import datetime, timezone
import time

from stock_agent.schemas.research_events import ResearchEvent, ResearchEventType

TERMINAL_EVENT_TYPES: set[ResearchEventType] = {
    "completed",
    "failed",
    "cancelled",
}

SUBSCRIBER_QUEUE_SIZE = 256
TERMINAL_TTL_SECONDS = 300
EVENT_STORE_CLEANUP_INTERVAL_SECONDS = 60

SubscriberQueue = asyncio.Queue[ResearchEvent | None]


class ResearchEventStore:
    """
    当前进程内的 Research Event Store。

    负责：
    - 为 thread 分配单调递增 event_id；
    - 保存短线重连需要的事件 buffer；
    - 向当前 SSE subscriber 实时广播。

    """

    def __init__(
        self,
        *,
        max_events_per_thread: int = 2000,
        subscriber_queue_size: int = SUBSCRIBER_QUEUE_SIZE,
        terminal_ttl_seconds: float = TERMINAL_TTL_SECONDS,
    ):
        self._max_events_per_thread = max_events_per_thread
        self._subscriber_queue_size = subscriber_queue_size
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._buffers: dict[str, deque[ResearchEvent]] = {}
        self._subscribers: dict[str, set[SubscriberQueue]] = {}
        self._last_event_ids: dict[str, int] = {}
        self._terminal_expires_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _close_subscriber_queue(self, queue: SubscriberQueue) -> None:
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(None)

    def _drop_thread_locked(self, thread_id: str) -> None:
        """真正删除一个 thread"""
        self._buffers.pop(thread_id, None)
        self._last_event_ids.pop(thread_id, None)
        self._terminal_expires_at.pop(thread_id, None)
        subscribers = self._subscribers.pop(thread_id, set())
        for queue in subscribers:
            self._close_subscriber_queue(queue)

    def _drop_expired_threads_locked(self) -> None:
        """删除过期 thread"""
        now = time.monotonic()
        expired_thread_ids = [
            thread_id
            for thread_id, expires_at in self._terminal_expires_at.items()
            if expires_at <= now
        ]
        for thread_id in expired_thread_ids:
            self._drop_thread_locked(thread_id)

    async def cleanup_expired(self) -> None:
        async with self._lock:
            self._drop_expired_threads_locked()

    async def publish(
        self,
        thread_id: str,
        event_type: ResearchEventType,
        data: dict | None = None,
    ) -> ResearchEvent:
        async with self._lock:
            self._drop_expired_threads_locked()
            event_id = self._last_event_ids.get(thread_id, 0) + 1
            event = ResearchEvent(
                event_id=event_id,
                thread_id=thread_id,
                type=event_type,
                data=dict(data or {}),
                created_at=datetime.now(timezone.utc),
            )

            # save
            buffer = self._buffers.get(thread_id)
            if buffer is None:
                buffer = deque(maxlen=self._max_events_per_thread)
                self._buffers[thread_id] = buffer
            buffer.append(event)

            self._last_event_ids[thread_id] = event_id

            # terminal event 时设置过期时间
            if event.type in TERMINAL_EVENT_TYPES:
                self._terminal_expires_at[thread_id] = time.monotonic() + self._terminal_ttl_seconds
            else:
                self._terminal_expires_at.pop(thread_id, None)

            # subscribers
            subscribers = self._subscribers.get(thread_id, set())
            overflowed: list[SubscriberQueue] = []
            for queue in subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    overflowed.append(queue)

            # 这个订阅者已经严重落后，无法继续可靠地接收事件，因此直接取消订阅。
            for queue in overflowed:
                subscribers.discard(queue)
                self._close_subscriber_queue(queue)

            if not subscribers:
                self._subscribers.pop(thread_id, None)

            return event

    async def subscribe(
        self,
        thread_id: str,
        *,
        last_event_id: int | None = None,
    ) -> tuple[SubscriberQueue, list[ResearchEvent], bool]:
        queue: SubscriberQueue = asyncio.Queue(maxsize=self._subscriber_queue_size)
        async with self._lock:
            self._drop_expired_threads_locked()
            subscribes = self._subscribers.setdefault(thread_id, set())
            subscribes.add(queue)

            buffer = list(self._buffers.get(thread_id, ()))

            if last_event_id is None:
                return queue, buffer, True

            replay_events = [event for event in buffer if event.event_id > last_event_id]
            last_published_id = self._last_event_ids.get(thread_id, 0)

            if last_published_id < last_event_id:
                replay_complete = False
            elif last_event_id == last_published_id:
                replay_complete = True
            elif not buffer:
                replay_complete = False
            else:
                first_buffered_id = buffer[0].event_id
                replay_complete = last_event_id >= first_buffered_id - 1

        return queue, replay_events, replay_complete

    async def unsubscribe(self, thread_id: str, queue: SubscriberQueue) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(thread_id, set())
            if not subscribers:
                return

            subscribers.discard(queue)

            if not subscribers:
                self._subscribers.pop(thread_id, None)


async def run_event_store_cleanup(event_store: ResearchEventStore) -> None:
    while True:
        await asyncio.sleep(EVENT_STORE_CLEANUP_INTERVAL_SECONDS)
        await event_store.cleanup_expired()
