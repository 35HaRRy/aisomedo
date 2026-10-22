"""One notification connection per process; bounded queues, never state polling."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any

import psycopg
from dojo.adapters.db import PostgresStore
from dojo.live import ChangeEvent

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15.0
QUEUE_SIZE = 64


@dataclass(frozen=True)
class StreamMessage:
    event: str
    data: dict[str, Any]


class LiveHub:
    def __init__(
        self, store: PostgresStore, *,
        connect: Callable[[], psycopg.Connection] | None = None,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._connect = connect or store.open_change_listener
        self._heartbeat = heartbeat_seconds
        self._now = now
        self._stop = Event()
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = asyncio.Event()
        self._subscribers: dict[asyncio.Queue[StreamMessage], int] = {}
        self._revoked_clients: set[int] = set()
        self._last_progress = time.monotonic()
        self.generation = 0
        self.ready = False

    async def start(self) -> None:
        if self._thread is None:
            self._loop = asyncio.get_running_loop()
            self._thread = Thread(target=self._listen, name="live-notifications", daemon=True)
            self._thread.start()
        await self._started.wait()

    async def close(self) -> None:
        self._stop.set()
        self.ready = False
        self.deliver("resync", {"reason": "server_shutdown"})
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 6)

    def _schedule(self, callback: Callable[..., None], *args: object) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(callback, *args)

    def _listener_ready(self) -> None:
        self._last_progress = time.monotonic()
        self.generation += 1
        self.ready = not self._stop.is_set()
        self._started.set()

    def _listener_progress(self) -> None:
        self._last_progress = time.monotonic()
        if not self.ready and self._started.is_set() and not self._stop.is_set():
            self._schedule(self._listener_ready)

    def _stalled(self) -> bool:
        return time.monotonic() - self._last_progress > max(self._heartbeat * 3, 1.0)

    def _listener_lost(self) -> None:
        self.generation += 1
        self.ready = False
        self._started.set()
        self.deliver("resync", {"reason": "listener_lost"})

    def _listen(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                with self._connect() as connection:
                    # Autocommit LISTEN is effective before the ready signal.
                    connection.execute("LISTEN dojo_changes")
                    self._schedule(self._listener_ready)
                    delay = 1.0
                    while not self._stop.is_set():
                        # Timeout only checks shutdown; no SQL/state query on idle.
                        self._listener_progress()
                        for notice in connection.notifies(timeout=1):
                            if self._stop.is_set():
                                break
                            event = self._store.get_change(notice.payload)
                            self._listener_progress()
                            self._schedule(self._committed_change, event)
            except Exception:  # noqa: BLE001 - loss requires resync, never a false heartbeat
                self._schedule(self._listener_lost)
                logger.warning("live listener disconnected", extra={"event": "live.listener_lost"})
            if not self._stop.is_set():
                self._stop.wait(delay * random.uniform(0.8, 1.2))
                delay = min(30.0, delay * 2)

    @staticmethod
    def _terminate(queue: asyncio.Queue[StreamMessage], reason: str) -> None:
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(StreamMessage("resync", {"reason": reason}))

    def _committed_change(self, event: ChangeEvent | None) -> None:
        if self._stop.is_set() or not self.ready:
            return
        if event is None:
            self.generation += 1
            self.deliver("resync", {"reason": "missing_event"})
            return
        self._revoked_clients.update(event.revoked_client_ids)
        for queue, client_id in list(self._subscribers.items()):
            if client_id in event.revoked_client_ids:
                self._terminate(queue, "unauthorized")
                self._subscribers.pop(queue, None)
        self.deliver("change", {"event_id": event.event_id, "versions": event.versions})

    def deliver(self, event: str, data: dict[str, Any]) -> None:
        """Loop-local fanout. Overflow is terminal, not dropped correctness data."""
        for queue in list(self._subscribers):
            if event == "resync" or queue.full():
                self._terminate(queue, str(data["reason"]) if event == "resync" else "overflow")
                self._subscribers.pop(queue, None)
            else:
                queue.put_nowait(StreamMessage(event, data))

    async def subscribe(
        self, client_id: int, *, expires_at: datetime | None,
    ) -> AsyncIterator[StreamMessage]:
        if client_id in self._revoked_clients:
            yield StreamMessage("resync", {"reason": "unauthorized"})
            return
        if not self.ready or self._stalled():
            if self.ready:
                self._listener_lost()
            yield StreamMessage("resync", {"reason": "listener_lost"})
            return
        queue: asyncio.Queue[StreamMessage] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers[queue] = client_id
        try:
            yield StreamMessage("ready", {"protocol": 1})
            while True:
                remaining = ((expires_at - self._now()).total_seconds()
                             if expires_at is not None else self._heartbeat)
                if remaining <= 0:
                    yield StreamMessage("resync", {"reason": "unauthorized"})
                    return
                try:
                    message = await asyncio.wait_for(queue.get(), min(self._heartbeat, remaining))
                except TimeoutError:
                    if expires_at is not None and self._now() >= expires_at:
                        yield StreamMessage("resync", {"reason": "unauthorized"})
                        return
                    if self._stalled():
                        self._listener_lost()
                        yield StreamMessage("resync", {"reason": "listener_lost"})
                        return
                    message = StreamMessage("heartbeat", {})
                yield message
                if message.event == "resync":
                    return
        finally:
            self._subscribers.pop(queue, None)
