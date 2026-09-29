"""Trusted proxy headers, secure cookies, and public-origin wiring (Task 5).

Real TestClient tests: forwarded client/scheme headers are honored only when
the immediate peer is in TRUSTED_PROXIES; forged headers from untrusted
sources are ignored. Cookie Secure issuance + renewal already default true.
"""

from __future__ import annotations

from pathlib import Path

from dojo import DojoPairing, InMemoryStore
from dojo.testing import FakeClock
from fastapi import Request
from fastapi.testclient import TestClient

from backend.main import create_app


def _scheme(request: Request) -> dict:
    return {"scheme": request.url.scheme}


def make_client(trusted_proxies: str, tmp_path: Path, **kwargs) -> TestClient:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    app = create_app(None, pairing, cookie_secure=True, trusted_proxies=trusted_proxies, **kwargs)
    # Test-only scheme echo: observes ASGI scheme after normalization.
    app.get("/_scheme")(_scheme)
    return TestClient(app)


def test_client_ip_uses_forwarded_header_only_from_trusted_proxy(tmp_path: Path) -> None:
    # Peer "testclient" is trusted: X-Forwarded-For selects the throttle identity.
    client = make_client("testclient", tmp_path)
    body = {"code": "aaaaaaaa", "kind": "device", "name": "X"}
    headers = {"X-Forwarded-For": "203.0.113.5"}
    for _ in range(10):
        assert client.post("/api/pairing/validate", json=body, headers=headers).status_code == 401
    assert client.post("/api/pairing/validate", json=body, headers=headers).status_code == 429
    # A different forwarded identity gets its own bucket (not throttled).
    other = {"X-Forwarded-For": "198.51.100.9"}
    assert client.post("/api/pairing/validate", json=body, headers=other).status_code == 401


def test_forged_forwarded_header_from_untrusted_source_ignored(tmp_path: Path) -> None:
    # Peer "testclient" is NOT trusted: X-Forwarded-For must not move identity.
    client = make_client("10.0.0.0/8", tmp_path)
    body = {"code": "aaaaaaaa", "kind": "device", "name": "X"}
    forged = {"X-Forwarded-For": "203.0.113.5"}
    for _ in range(10):
        assert client.post("/api/pairing/validate", json=body, headers=forged).status_code == 401
    # 11th request with a *different* forged header still hits the same
    # direct-peer bucket -> throttled, proving the header was ignored.
    other_forged = {"X-Forwarded-For": "198.51.100.9"}
    assert client.post("/api/pairing/validate", json=body, headers=other_forged).status_code == 429


def test_multi_hop_chain_resolves_last_untrusted_hop(tmp_path: Path) -> None:
    # Only the immediate peer is trusted: identity is the last untrusted hop.
    client = make_client("testclient", tmp_path)
    body = {"code": "aaaaaaaa", "kind": "device", "name": "X"}
    chain = {"X-Forwarded-For": "203.0.113.5, 198.51.100.9"}
    for _ in range(10):
        assert client.post("/api/pairing/validate", json=body, headers=chain).status_code == 401
    assert client.post("/api/pairing/validate", json=body, headers=chain).status_code == 429
    # Same origin behind a different last hop is a different bucket.
    other = {"X-Forwarded-For": "203.0.113.5, 192.0.2.7"}
    assert client.post("/api/pairing/validate", json=body, headers=other).status_code == 401


def test_direct_untrusted_request_without_headers_uses_peer_identity(tmp_path: Path) -> None:
    client = make_client("10.0.0.0/8", tmp_path)
    body = {"code": "aaaaaaaa", "kind": "device", "name": "X"}
    for _ in range(10):
        assert client.post("/api/pairing/validate", json=body).status_code == 401
    assert client.post("/api/pairing/validate", json=body).status_code == 429


def test_https_scheme_detected_only_from_trusted_proxy(tmp_path: Path) -> None:
    trusted = make_client("testclient", tmp_path)
    https = {"X-Forwarded-Proto": "https"}
    assert trusted.get("/_scheme", headers=https).json() == {"scheme": "https"}
    untrusted = make_client("10.0.0.0/8", tmp_path)
    assert untrusted.get("/_scheme", headers=https).json() == {"scheme": "http"}


def test_secure_cookie_preserved_behind_https_proxy(tmp_path: Path) -> None:
    # Issuance: browser pairing behind an https-terminating trusted proxy.
    client = make_client("testclient", tmp_path)
    store_pairing: DojoPairing = client.app.state.pairing
    code = store_pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post(
        "/api/pairing/validate",
        json={"code": code, "kind": "browser", "name": "Browser"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200
    assert "secure" in resp.headers["set-cookie"].lower()
    # Renewal: authenticated request re-issues the session cookie, still Secure.
    # (Secure cookies are not auto-sent by the jar over the http TestClient
    # base URL — correct browser behavior — so replay via Cookie header.)
    session_id = resp.cookies.get("dojo_session")
    assert session_id is not None
    renewed = client.get(
        "/api/pairing/me",
        headers={"Cookie": f"dojo_session={session_id}", "X-Forwarded-Proto": "https"},
    )
    assert renewed.status_code == 200
    assert "secure" in renewed.headers["set-cookie"].lower()


def test_public_origin_prefers_https_origin_env(monkeypatch, tmp_path: Path) -> None:
    from backend import deps

    monkeypatch.setenv("PUBLIC_HTTPS_ORIGIN", "https://dojo.example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    assert deps.resolve_public_base_url() == "https://dojo.example.com"
    monkeypatch.delenv("PUBLIC_HTTPS_ORIGIN")
    assert deps.resolve_public_base_url() == "http://localhost:8000"


def test_public_origin_rejects_http_when_secure(monkeypatch, tmp_path: Path) -> None:
    import pytest

    from backend import deps
    from backend.main import create_app as _create

    monkeypatch.setenv("PUBLIC_HTTPS_ORIGIN", "http://dojo.example.com")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    with pytest.raises(RuntimeError, match="non-https public origin"):
        deps.resolve_public_base_url()
    # Startup fails fast through create_app.
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    with pytest.raises(RuntimeError, match="non-https public origin"):
        _create(None, pairing, cookie_secure=True, trusted_proxies="testclient")
    # Dev localhost default unaffected even while secure.
    monkeypatch.delenv("PUBLIC_HTTPS_ORIGIN")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert deps.resolve_public_base_url() == "http://localhost:8000"
    # Explicit opt-out (COOKIE_SECURE=false) allows http.
    monkeypatch.setenv("PUBLIC_HTTPS_ORIGIN", "http://dojo.example.com")
    assert deps.resolve_public_base_url(False) == "http://dojo.example.com"


def test_build_publishing_bad_origin_raises_despite_secret(
    monkeypatch, tmp_path: Path
) -> None:
    """Misconfigured origin must raise, not silently drop the signed-URL store.

    Regression pin: resolve_public_base_url() used to sit inside the
    try/except-pass, so direct build_publishing() misuse fell back to the
    stub. Stub fallback applies only when no secret is configured.
    """
    import pytest

    from backend import deps

    monkeypatch.setenv("SKIP_CREATE_ALL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://127.0.0.1:1/unreachable")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("SIGNED_URL_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_HTTPS_ORIGIN", "http://dojo.example.com")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.delenv("META_TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="non-https public origin"):
        deps.build_publishing()


def test_trusted_proxies_typo_fails_at_startup(tmp_path: Path) -> None:
    import pytest
    from dojo import DojoPairing, InMemoryStore
    from dojo.testing import FakeClock

    from backend.main import create_app as _create
    from backend.proxy import ProxyHeadersMiddleware

    async def _noop(scope, receive, send): ...  # noqa: ANN001, ANN202

    with pytest.raises(ValueError, match="invalid TRUSTED_PROXIES"):
        ProxyHeadersMiddleware(_noop, trusted_proxies="not-a-cidr")
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    with pytest.raises(ValueError, match="invalid TRUSTED_PROXIES"):
        _create(None, pairing, cookie_secure=True, trusted_proxies="not-a-cidr")
    # Per-request path never raises on config: garbage headers are ignored.
    client = make_client("10.0.0.0/8", tmp_path)
    resp = client.get(
        "/_scheme",
        headers={"X-Forwarded-For": "garbage!!!", "X-Forwarded-Proto": "gopher"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"scheme": "http"}
