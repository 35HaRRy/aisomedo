from __future__ import annotations

import httpx
import pytest
from dojo import InMemoryStore, MetaPublishFailed, MetaPublishUncertain
from dojo.adapters.meta import FernetCipher, HttpMetaPublisher
from dojo.testing import FIXED_AT


def make_publisher(handler) -> tuple[HttpMetaPublisher, InMemoryStore]:
    store = InMemoryStore()
    cipher = FernetCipher(FernetCipher.generate_key())
    store.upsert_active(
        ig_user_id="ig_123",
        ig_username="dojo",
        page_id=None,
        page_name=None,
        encrypted_token=cipher.encrypt("token_abc"),
        token_expires_at=None,
        health="healthy",
        last_checked_at=FIXED_AT,
        last_refreshed_at=None,
        last_error=None,
    )
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    publisher = HttpMetaPublisher(
        connection_store=store, cipher=cipher, http_client=client
    )
    return publisher, store


def ok_json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_create_poll_publish_happy_path():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/media") and request.method == "POST":
            return ok_json({"id": "container_1"})
        if request.url.path.endswith("/container_1") and request.method == "GET":
            return ok_json({"status_code": "FINISHED"})
        if request.url.path.endswith("/media_publish"):
            return ok_json({"id": "media_9"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    publisher, _ = make_publisher(handler)
    assert publisher.create_container("https://signed/x", "cap") == "container_1"
    assert publisher.get_container_status("container_1") == "FINISHED"
    assert publisher.publish_container("container_1") == "media_9"
    assert len(calls) == 3


def test_transient_becomes_uncertain_definitive_becomes_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media"):
            return ok_json({"error": {"code": 4, "message": "busy"}}, status=500)
        raise AssertionError("unexpected")

    publisher, _ = make_publisher(handler)
    with pytest.raises(MetaPublishUncertain):
        publisher.create_container("https://signed/x", "cap")

    def handler2(request: httpx.Request) -> httpx.Response:
        return ok_json({"error": {"code": 100, "message": "bad"}})

    publisher2, _ = make_publisher(handler2)
    with pytest.raises(MetaPublishFailed):
        publisher2.create_container("https://signed/x", "cap")


def test_timeout_is_uncertain():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    publisher, _ = make_publisher(handler)
    with pytest.raises(MetaPublishUncertain):
        publisher.publish_container("container_1")
