from datetime import UTC, datetime, timedelta

import httpx
import pytest
from dojo.adapters import meta as adapters
from dojo.adapters.memory import InMemoryStore
from dojo.meta_connection import DojoMetaConnection
from dojo.testing import FakeClock

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
TOKEN = "instagram-private-token"


def make_connection(handler, store=None, clock=None):
    provider_class = getattr(adapters, "HttpInstagramTokenProvider", None)
    assert provider_class is not None, "Instagram Login provider must exist"
    clock = clock or FakeClock(NOW)
    provider = provider_class(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), clock=clock
    )
    store = store or InMemoryStore()
    cipher = adapters.FernetCipher(adapters.FernetCipher.generate_key())
    facebook = adapters.StubMetaOAuthProvider()
    service = DojoMetaConnection(
        store=store, provider=facebook, instagram_provider=provider,
        cipher=cipher, audit=store, clock=clock,
        app_id="app", app_secret="secret", redirect_uri="https://example.test/callback",
    )
    return service, store, cipher, facebook, clock


def instagram_response(request):
    assert request.url.host == "graph.instagram.com"
    if request.url.path.endswith("/me"):
        assert "authorization" not in request.headers
        assert request.url.params["access_token"] == TOKEN
        assert request.url.params["fields"] == "user_id,username"
        return httpx.Response(200, json={"user_id": "178414000000001", "username": "dojo"})
    if request.url.path == "/refresh_access_token":
        assert request.url.params["grant_type"] == "ig_refresh_token"
        return httpx.Response(200, json={
            "access_token": "renewed-private-token", "token_type": "bearer", "expires_in": 5180000,
        })
    raise AssertionError(f"Unexpected request path: {request.url.path}")


def test_import_discovers_account_encrypts_token_and_does_not_invent_expiry():
    service, store, cipher, facebook, _ = make_connection(instagram_response)
    status = service.connect_instagram_token(7, TOKEN)
    assert status.ig_user_id == "178414000000001"
    assert status.ig_username == "dojo"
    assert status.connection_type == "instagram_login"
    assert status.page_id is None and status.page_name is None
    assert status.expires_at is None
    encrypted, expiry = store.get_raw_active()
    assert encrypted != TOKEN and cipher.decrypt(encrypted) == TOKEN
    assert expiry is None
    assert service.get_valid_token() == TOKEN
    assert service.get_status().connection_type == "instagram_login"
    assert TOKEN not in str(status.to_dict())
    assert TOKEN not in str(store.list_recent())
    assert facebook.calls == []


@pytest.mark.parametrize("failure", ["invalid", "timeout", "malformed"])
def test_failed_import_preserves_active_connection_and_hides_secrets(failure):
    service, store, _, _, _ = make_connection(instagram_response)
    service.connect_instagram_token(7, TOKEN)
    before = store.get_raw_active()

    def rejected(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(f"failed {TOKEN}", request=request)
        if failure == "invalid":
            return httpx.Response(400, json={"error": {"code": 190, "message": TOKEN}})
        if failure == "malformed":
            return httpx.Response(200, json={"username": "no-id"})
        return instagram_response(request)

    other, _, _, _, _ = make_connection(rejected, store=store)
    with pytest.raises(Exception) as error:
        other.connect_instagram_token(7, TOKEN)
    assert TOKEN not in str(error.value)
    assert store.get_raw_active() == before
    assert service.get_status().ig_user_id == "178414000000001"


def test_unknown_expiry_waits_one_day_then_refreshes_via_instagram():
    service, store, cipher, facebook, clock = make_connection(instagram_response)
    service.connect_instagram_token(7, TOKEN)
    service.maintain()
    assert cipher.decrypt(store.get_raw_active()[0]) == TOKEN
    clock._now = NOW + timedelta(days=1)
    status = service.maintain()
    assert status.health == "healthy"
    assert status.connection_type == "instagram_login"
    assert status.expires_at == clock.now() + timedelta(seconds=5180000)
    assert cipher.decrypt(store.get_raw_active()[0]) == "renewed-private-token"
    assert facebook.calls == []


@pytest.mark.parametrize("http_status,code,expected", [
    (400, 190, "reconnect_required"), (429, 4, "healthy"), (503, 2, "healthy"),
])
def test_maintenance_distinguishes_revocation_from_transient_failure(http_status, code, expected):
    failed = False

    def handler(request):
        if failed:
            return httpx.Response(http_status, json={"error": {"code": code, "message": TOKEN}})
        return instagram_response(request)

    service, store, _, facebook, clock = make_connection(handler)
    service.connect_instagram_token(7, TOKEN)
    failed = True
    clock._now = NOW + timedelta(days=1)
    status = service.maintain()
    assert status.health == expected
    assert status.connection_type == "instagram_login"
    assert TOKEN not in str(status.last_error)
    assert facebook.calls == []
    assert store.get_raw_active() is not None


def test_facebook_oauth_flow_remains_available_after_instagram_import():
    service, _, _, facebook, _ = make_connection(instagram_response)
    service.connect_instagram_token(7, TOKEN)
    url, attempt_id = service.start(7)
    state = httpx.URL(url).params["state"]
    assert service.complete_callback(state, "code") == attempt_id
    status = service.select_account(7, attempt_id, "ig_123")
    assert status.connection_type == "facebook_login"
    assert status.page_id == "page_1"
    assert "exchange_code" in facebook.calls


@pytest.mark.parametrize("outcome", ["refresh", "invalid"])
def test_in_flight_maintenance_cannot_overwrite_a_new_connection(outcome):
    replacing = False

    def handler(request):
        nonlocal replacing
        token = request.url.params.get("access_token")
        if token == "replacement-token":
            return httpx.Response(200, json={"user_id": "178414000000002", "username": "new"})
        if replacing and request.url.path.endswith("/me"):
            replacing = False
            service.connect_instagram_token(7, "replacement-token")
            if outcome == "invalid":
                return httpx.Response(400, json={"error": {"code": 190}})
        return instagram_response(request)

    service, store, cipher, _, clock = make_connection(handler)
    service.connect_instagram_token(7, TOKEN)
    clock._now = NOW + timedelta(days=1)
    replacing = True
    status = service.maintain()
    assert status.ig_user_id == "178414000000002"
    assert status.health == "healthy"
    assert cipher.decrypt(store.get_raw_active()[0]) == "replacement-token"


def test_non_ascii_token_rejected_before_http_request():
    service, _, _, _, _ = make_connection(instagram_response)
    from dojo.exceptions import MetaTokenInvalid

    with pytest.raises(MetaTokenInvalid):
        service.connect_instagram_token(7, "private-ş-token")
