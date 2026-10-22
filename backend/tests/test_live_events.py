import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from dojo.adapters.db import PostgresStore
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from backend.live import LiveHub


@pytest.fixture(scope="module")
def live_store():
    with PostgresContainer("postgres:18") as pg:
        store = PostgresStore(pg.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+psycopg://",
        ))
        store.create_all()
        yield store
        store.dispose()


async def change(store, resources=None, revoked=None):
    def commit():
        with store.command_transaction():
            return store.record_change(resources or ["dashboard"], revoked_client_ids=revoked)
    return await asyncio.to_thread(commit)


async def next_message(stream):
    return await asyncio.wait_for(anext(stream), 3)


def test_listener_accepts_driver_options_without_duplicate_keyword_arguments(live_store):
    url = live_store._engine.url.update_query_dict({"connect_timeout": "3", "keepalives": "1"})
    configured = PostgresStore(url.render_as_string(hide_password=False))
    try:
        with configured.open_change_listener() as connection:
            assert connection.autocommit
            assert connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        configured.dispose()


@pytest.mark.asyncio
async def test_one_committed_listener_serves_ten_registered_subscribers(live_store):
    connections = []

    def connect():
        conn = live_store.open_change_listener()
        connections.append(conn)
        return conn

    hub = LiveHub(live_store, connect=connect)
    await hub.start()
    streams = [hub.subscribe(i, expires_at=None) for i in range(10)]
    try:
        assert hub.ready
        for stream in streams:
            first = await next_message(stream)
            assert first.event == "ready" and first.data == {"protocol": 1}
        event = await change(live_store)
        for stream in streams:
            message = await next_message(stream)
            assert message.event == "change"
            assert message.data == {"event_id": event.event_id, "versions": event.versions}
        assert len(connections) == 1
    finally:
        for stream in streams:
            await stream.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_rollback_never_reaches_stream_and_heartbeat_does_not_query(live_store, monkeypatch):
    statements = []

    class ObservedConnection:
        def __init__(self):
            self.connection = live_store.open_change_listener()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.connection.close()

        def execute(self, statement):
            statements.append(statement)
            return self.connection.execute(statement)

        def notifies(self, **kwargs):
            return self.connection.notifies(**kwargs)

    hub = LiveHub(live_store, connect=ObservedConnection, heartbeat_seconds=0.03)
    await hub.start()
    stream = hub.subscribe(1, expires_at=None)
    try:
        await next_message(stream)
        def rollback():
            with pytest.raises(ValueError):
                with live_store.command_transaction():
                    live_store.record_change(["dashboard"])
                    raise ValueError("reject")
        await asyncio.to_thread(rollback)
        def forbidden(*args, **kwargs):
            raise AssertionError("idle heartbeat must not read database state")
        monkeypatch.setattr(live_store, "get_change", forbidden)
        monkeypatch.setattr(live_store, "get_resource_version", forbidden)
        assert (await next_message(stream)).event == "heartbeat"
        assert (await next_message(stream)).event == "heartbeat"
        assert statements == ["LISTEN dojo_changes"]
    finally:
        await stream.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_revocation_closes_only_target_stream_without_broadcast_identity(live_store):
    hub = LiveHub(live_store)
    await hub.start()
    revoked = hub.subscribe(7, expires_at=None)
    other = hub.subscribe(8, expires_at=None)
    try:
        await next_message(revoked)
        await next_message(other)
        await change(live_store, ["auth"], [7])
        message = await next_message(revoked)
        assert message.event == "resync" and message.data == {"reason": "unauthorized"}
        with pytest.raises(StopAsyncIteration):
            await anext(revoked)
        message = await next_message(other)
        assert message.event == "change"
        assert set(message.data) == {"event_id", "versions"}
    finally:
        await revoked.aclose()
        await other.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_revocation_between_authentication_and_registration_cannot_open_stream(live_store):
    hub = LiveHub(live_store)
    await hub.start()
    observer = hub.subscribe(8, expires_at=None)
    try:
        await next_message(observer)
        await change(live_store, ["auth"], [7])
        assert (await next_message(observer)).event == "change"
        # This request authenticated before the revocation but only registers
        # now. Authentication on establishment alone must not leave it live.
        late = hub.subscribe(7, expires_at=None)
        try:
            message = await next_message(late)
            assert message.event == "resync" and message.data == {"reason": "unauthorized"}
        finally:
            await late.aclose()
    finally:
        await observer.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_listener_restart_during_authentication_requires_fresh_establishment(
    tmp_path, live_store,
):
    import httpx
    from fastapi import Request
    from test_package_editor_api import app

    from backend.deps import get_current_client

    paired, _, pairing, client_id, _ = app(tmp_path)
    hub = LiveHub(live_store)
    paired.app.state.live_hub = hub
    await hub.start()

    async def authenticate(request: Request):
        request.state.authorization_expires_at = None
        request.state.live_generation = hub.generation
        hub._listener_lost()
        hub._listener_ready()
        return pairing._pairing.find_client_by_id(client_id)

    paired.app.dependency_overrides[get_current_client] = authenticate
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=paired.app),
                                     base_url="http://testserver") as client:
            response = await asyncio.wait_for(client.get("/api/events"), 2)
            assert response.status_code == 503
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_expiration_terminates_without_a_database_query(live_store):
    hub = LiveHub(live_store)
    await hub.start()
    stream = hub.subscribe(1, expires_at=datetime.now(UTC) + timedelta(milliseconds=30))
    try:
        await next_message(stream)
        message = await next_message(stream)
        assert message.event == "resync" and message.data == {"reason": "unauthorized"}
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await stream.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_missing_event_lookup_forces_resynchronization(live_store):
    hub = LiveHub(live_store)
    await hub.start()
    stream = hub.subscribe(1, expires_at=None)
    try:
        await next_message(stream)
        def notify():
            with live_store._engine.begin() as conn:
                conn.execute(text("SELECT pg_notify('dojo_changes', 'missing-event')"))
        await asyncio.to_thread(notify)
        message = await next_message(stream)
        assert message.event == "resync" and message.data == {"reason": "missing_event"}
    finally:
        await stream.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_sixty_four_message_overflow_is_not_silent(live_store):
    hub = LiveHub(live_store)
    await hub.start()
    stream = hub.subscribe(1, expires_at=None)
    try:
        await next_message(stream)
        # Fanout on the actual loop without letting the deliberately slow
        # consumer drain its bounded queue.
        for i in range(65):
            hub.deliver("change", {"event_id": str(i), "versions": {"dashboard": i + 1}})
        message = await next_message(stream)
        assert message.event == "resync" and message.data == {"reason": "overflow"}
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await stream.aclose()
        await hub.close()


@pytest.mark.asyncio
async def test_database_listener_loss_closes_dependent_stream(live_store):
    connections = []
    def connect():
        conn = live_store.open_change_listener()
        connections.append(conn)
        return conn
    hub = LiveHub(live_store, connect=connect)
    await hub.start()
    stream = hub.subscribe(1, expires_at=None)
    try:
        await next_message(stream)
        pid = connections[0].info.backend_pid
        def terminate():
            with live_store._engine.begin() as conn:
                conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        await asyncio.to_thread(terminate)
        message = await next_message(stream)
        assert message.event == "resync" and message.data == {"reason": "listener_lost"}
    finally:
        await stream.aclose()
        await hub.close()


def test_sse_establishment_requires_existing_authentication(tmp_path):
    from test_package_editor_api import app
    client, _, _, _, _ = app(tmp_path)
    client.cookies.clear()
    response = client.get("/api/events")
    assert response.status_code == 401


def test_real_http_stream_renews_cookie_and_delivers_commit_then_revocation(tmp_path, live_store):
    import json
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from test_package_editor_api import app

    paired, _, pairing, client_id, _ = app(tmp_path)
    hub = LiveHub(live_store, now=pairing._clock.now)
    paired.app.state.live_hub = hub
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(paired.app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/api/events"
        with httpx.Client(cookies={"dojo_session": paired.cookies.get("dojo_session")},
                          timeout=3) as client:
            with client.stream("GET", url) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["x-accel-buffering"] == "no"
                assert "dojo_session=" in response.headers["set-cookie"]
                lines = response.iter_lines()

                def frame():
                    event, data = None, None
                    for line in lines:
                        if line.startswith("event: "):
                            event = line[7:]
                        elif line.startswith("data: "):
                            data = json.loads(line[6:])
                        elif not line and event is not None:
                            return event, data
                    raise AssertionError("stream ended before a complete frame")

                assert frame() == ("ready", {"protocol": 1})
                with live_store.command_transaction():
                    event = live_store.record_change(["dashboard"])
                assert frame() == ("change", {"event_id": event.event_id,
                                               "versions": event.versions})
                with live_store.command_transaction():
                    live_store.record_change(["auth"], revoked_client_ids=[client_id])
                assert frame() == ("resync", {"reason": "unauthorized"})
                assert list(lines) == []
    finally:
        server.should_exit = True
        thread.join(8)
        listener.close()
        assert not thread.is_alive()
