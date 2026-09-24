import httpx
import pytest
from dojo import DojoMetaConnection, DojoPairing, InMemoryStore
from dojo.adapters import meta as adapters
from fastapi.testclient import TestClient

from backend.main import create_app


def make_api():
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store)
    meta = DojoMetaConnection(
        store=store, provider=adapters.StubMetaOAuthProvider(),
        cipher=adapters.FernetCipher(adapters.FernetCipher.generate_key()),
        app_id="app", app_secret="secret", redirect_uri="https://example.test/callback",
    )
    client = TestClient(create_app(pairing=pairing, meta=meta, cookie_secure=False))
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = client.post("/api/pairing/validate", json={
        "code": code, "kind": "device", "name": "PowerShell",
    })
    headers = {"Authorization": f"Bearer {result.json()['token']}"}
    return client, meta, headers


def test_token_import_requires_app_authentication():
    client, _, _ = make_api()
    response = client.post("/api/meta/instagram/token", json={"access_token": "private"})
    assert response.status_code == 401


@pytest.mark.parametrize("body", [{}, {"access_token": " "}, {"access_token": 123},
                                  {"access_token": {"value": "private"}}])
def test_invalid_body_never_echoes_submitted_token(body):
    client, _, headers = make_api()
    response = client.post("/api/meta/instagram/token", headers=headers, json=body)
    assert response.status_code == 422
    assert "private" not in response.text


def test_real_token_import_returns_discovered_id_without_token():
    client, meta, headers = make_api()
    provider_class = getattr(adapters, "HttpInstagramTokenProvider", None)
    assert provider_class is not None

    def handler(request):
        return httpx.Response(200, json={"user_id": "178414000000001", "username": "dojo"})

    meta._instagram_provider = provider_class(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    response = client.post("/api/meta/instagram/token", headers=headers,
                           json={"access_token": "private-instagram-token"})
    assert response.status_code == 200
    assert response.json()["ig_user_id"] == "178414000000001"
    assert response.json()["connection_type"] == "instagram_login"
    assert response.json()["page_id"] is None
    assert "private-instagram-token" not in response.text
    assert client.get("/api/meta/status", headers=headers).json() == response.json()


@pytest.mark.parametrize("status,code,expected", [(400, 190, 422), (503, 2, 502)])
def test_provider_failure_is_safe_and_does_not_connect(status, code, expected):
    client, meta, headers = make_api()
    meta._instagram_provider = adapters.HttpInstagramTokenProvider(
        http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            status, json={"error": {"code": code, "message": "private-token"}},
        )))
    )
    response = client.post("/api/meta/instagram/token", headers=headers,
                           json={"access_token": "private-token"})
    assert response.status_code == expected
    assert "private-token" not in response.text
    assert meta.get_status().health == "not_connected"
