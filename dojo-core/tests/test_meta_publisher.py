from __future__ import annotations

import httpx
import pytest
from dojo import InMemoryStore, MetaPublishFailed, MetaPublishUncertain
from dojo.adapters.meta import FernetCipher, HttpMetaPublisher
from dojo.testing import FIXED_AT


def make_publisher(
    handler, connection_type="facebook_login"
) -> tuple[HttpMetaPublisher, InMemoryStore]:
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
        connection_type=connection_type,
    )
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    publisher = HttpMetaPublisher(
        connection_store=store, cipher=cipher, http_client=client
    )
    return publisher, store


def ok_json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


@pytest.mark.parametrize("connection_type, host", [
    ("facebook_login", "graph.facebook.com"),
    ("instagram_login", "graph.instagram.com"),
])
def test_create_poll_publish_happy_path(connection_type, host):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == host
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/media") and request.method == "POST":
            return ok_json({"id": "container_1"})
        if request.url.path.endswith("/container_1") and request.method == "GET":
            return ok_json({"status_code": "FINISHED"})
        if request.url.path.endswith("/media_publish"):
            return ok_json({"id": "media_9"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    publisher, _ = make_publisher(handler, connection_type)
    assert publisher.create_container("https://videos.example.test/x", "cap") == "container_1"
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
        publisher.create_container("https://videos.example.test/x", "cap")

    def handler2(request: httpx.Request) -> httpx.Response:
        return ok_json({"error": {"code": 100, "message": "bad"}})

    publisher2, _ = make_publisher(handler2)
    with pytest.raises(MetaPublishFailed):
        publisher2.create_container("https://videos.example.test/x", "cap")


def test_timeout_is_uncertain():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    publisher, _ = make_publisher(handler)
    with pytest.raises(MetaPublishUncertain):
        publisher.publish_container("container_1")


@pytest.mark.parametrize("url", [
    "http://videos.example.com/pub/token",
    "http://localhost:8000/pub/token",
    "https://localhost/pub/token",
    "https://LOCALHOST./pub/token",
    "https://dojo.localhost/pub/token",
    "https://dojo.local/pub/token",
    "https://127.0.0.1/pub/token",
    "https://127.1/pub/token",
    "https://2130706433/pub/token",
    "https://0x7f.0.0.1/pub/token",
    "https://backend/pub/token",
    "https://192.168.1.10/pub/token",
    "https://[::1]/pub/token",
    "https://[fd00::1]/pub/token",
    "/pub/token",
    "https://user:secret@videos.example.com/pub/token",
    "https://[invalid/pub/token",
    "https://videos.example.com:invalid/pub/token",
    "https://videos.example.com:65536/pub/token",
])
def test_non_public_video_url_fails_without_sending_to_meta(url):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return ok_json({"id": "should_not_be_created"})

    publisher, _ = make_publisher(handler, "instagram_login")
    with pytest.raises(MetaPublishFailed, match="publicly reachable HTTPS") as failure:
        publisher.create_container(url, "caption")
    assert calls == []
    assert "PUBLIC_BASE_URL" in str(failure.value)
    assert "token" not in str(failure.value)
