import asyncio
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.live import LiveHub


@pytest.mark.asyncio
async def test_stalled_event_lookup_stops_heartbeats_and_readiness():
    entered, release = Event(), Event()

    class Store:
        def get_change(self, event_id: str) -> None:
            entered.set()
            assert release.wait(5), "test must release the lookup"
            return None

    class Connection:
        sent = False

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: str) -> None:
            return None

        def notifies(self, timeout: float = 1) -> list[SimpleNamespace]:
            if not self.sent:
                self.sent = True
                return [SimpleNamespace(payload="event")]
            return []

    hub = LiveHub(
        cast(Any, Store()),
        connect=cast(Any, lambda: Connection()),
        heartbeat_seconds=0.2,
    )
    await hub.start()
    stream = hub.subscribe(1, expires_at=None)
    assert (await asyncio.wait_for(anext(stream), 3)).event == "ready"
    assert await asyncio.to_thread(entered.wait, 2)

    while True:
        message = await asyncio.wait_for(anext(stream), 3)
        if message.event == "resync":
            assert message.data["reason"] == "listener_lost"
            break
        assert message.event == "heartbeat"

    assert not hub.ready
    release.set()
    await hub.close()
