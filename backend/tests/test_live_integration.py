"""Real HTTP, independent API processes, a worker process, and PostgreSQL LISTEN."""

import hashlib
import json
import multiprocessing
import socket
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import httpx
from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup
from dojo.adapters.db import PostgresStore
from dojo.adapters.stubs import StubMediaProcessor
from dojo.testing import FakeClock
from sqlalchemy import text
from test_live_events import live_store  # noqa: F401


def publishing(store, root):
    return DojoPublishing(
        packages=store, audit=store, settings=store, media_root=Path(root),
        clock=FakeClock(), media=StubMediaProcessor(content_type="video/mp4", duration=30),
    )


def serve(url, root, pipe):
    import uvicorn

    from backend.live import LiveHub
    from backend.main import create_app

    store = PostgresStore(url)
    app = create_app(
        publishing(store, root), DojoPairing(pairing=store, audit=store, clock=FakeClock()),
        DojoActivity(audit=store, pairing=store),
        DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock()),
        cookie_secure=False, readiness=lambda: True,
    )

    def connect():
        connection = store.open_change_listener()
        pipe.send(("listener", connection.info.backend_pid))
        return connection

    app.state.live_hub = LiveHub(store, connect=connect)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        pipe.send(("port", listener.getsockname()[1]))
        uvicorn.Server(uvicorn.Config(app, log_level="error")).run(sockets=[listener])


def worker(url, root, captions):
    store = PostgresStore(url)
    try:
        domain = publishing(store, root)
        job = domain.claim_next_job()
        if job is not None:
            domain.process_job(job.job_id)
        for caption in captions:
            domain.set_caption(caption, requester="integration-worker")
    finally:
        store.dispose()


@contextmanager
def api_process(context, url, root):
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=serve, args=(url, str(root), send))
    process.start()
    send.close()
    try:
        messages = {}
        deadline = time.monotonic() + 15
        while len(messages) < 2:
            assert receive.poll(max(0, deadline - time.monotonic())), "API listener failed to start"
            key, value = receive.recv()
            messages[key] = value
        base = f"http://127.0.0.1:{messages['port']}"
        while True:
            try:
                if httpx.get(base + "/api/compat", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            assert time.monotonic() < deadline
            time.sleep(0.02)
        yield base, messages["listener"], process.pid
    finally:
        process.terminate()
        process.join(10)
        receive.close()
        assert not process.is_alive()


def frame(lines):
    event, data = None, None
    for line in lines:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
        elif not line and event is not None:
            return event, data
    raise AssertionError("Stream closed without a frame")


def test_two_api_processes_observe_worker_burst_reconnect_and_revocation(live_store, tmp_path):  # noqa: F811
    store = live_store
    url = store._engine.url.render_as_string(hide_password=False)
    domain = publishing(store, tmp_path)
    data = b"fixture" * 20
    upload = domain.start_upload("worker.mp4", "video/mp4", len(data))
    domain.append_upload_range(
        upload.upload_id, 0, len(data), hashlib.sha256(data).hexdigest(), data,
    )
    domain.complete_upload(upload.upload_id)
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    code = pairing.create_pairing_code(requester="integration").raw_code
    context = multiprocessing.get_context("spawn")
    with (
        api_process(context, url, tmp_path) as first,
        api_process(context, url, tmp_path) as second,
    ):
        assert first[2] != second[2]
        paired = httpx.post(first[0] + "/api/pairing/validate", json={
            "code": code, "kind": "device", "name": "Integration device",
        })
        assert paired.status_code == 200
        headers = {
            "Authorization": f"Bearer {paired.json()['token']}", "X-Android-Version-Code": "1",
        }
        with ExitStack() as stack:
            clients = [
                stack.enter_context(httpx.Client(base_url=api[0], headers=headers, timeout=5))
                for api in (first, second)
            ]
            responses = [
                stack.enter_context(client.stream("GET", "/api/events")) for client in clients
            ]
            streams = [response.iter_lines() for response in responses]
            for response, lines in zip(responses, streams, strict=True):
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["x-accel-buffering"] == "no"
                assert frame(lines) == ("ready", {"protocol": 1})
            process = context.Process(
                target=worker, args=(url, str(tmp_path), [f"burst-{i}" for i in range(10)]),
            )
            process.start()
            process.join(15)
            if process.is_alive():
                process.terminate()
                process.join(5)
                raise AssertionError("Worker did not finish")
            assert not process.is_alive() and process.exitcode == 0
            package = domain.get_active_package()
            key = f"package:{package.id}"
            version = store.get_resource_version(key)
            for client, lines in zip(clients, streams, strict=True):
                observed = 0
                while observed < version:
                    event, payload = frame(lines)
                    assert event == "change"
                    observed = max(observed, payload["versions"].get(key, 0))
                snapshot = client.get("/api/packages/active/editor")
                assert snapshot.status_code == 200
                assert snapshot.json()["media"][0]["status"] == "finalized"
                caption = client.get("/api/packages/active/caption")
                assert caption.json() == {"caption": "burst-9"}
                assert int(caption.headers["X-Resource-Version"]) == version

            # Break only the first API's dedicated LISTEN socket in this isolated test database.
            with store._engine.begin() as connection:
                connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": first[1]})
            assert frame(streams[0]) == ("resync", {"reason": "listener_lost"})
            assert list(streams[0]) == []
            deadline = time.monotonic() + 10
            while True:
                manager = clients[0].stream("GET", "/api/events")
                response = manager.__enter__()
                if response.status_code == 200:
                    stack.callback(manager.__exit__, None, None, None)
                    break
                manager.__exit__(None, None, None)
                assert time.monotonic() < deadline
                time.sleep(0.05)
            streams[0] = response.iter_lines()
            assert frame(streams[0]) == ("ready", {"protocol": 1})
            assert clients[0].get("/api/packages/active/caption").json() == {"caption": "burst-9"}
            pairing.revoke_client(client_id=paired.json()["client_id"], requester="integration")
            for lines in streams:
                # Audit invalidations may precede the targeted terminal authentication event.
                while True:
                    event, payload = frame(lines)
                    if event == "resync":
                        assert payload == {"reason": "unauthorized"}
                        break
                assert list(lines) == []
            assert clients[0].get("/api/events").status_code == 401
