from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from dojo import (
    ClientNotFound,
    DojoPairing,
    PairingCodeConsumed,
    PairingCodeExpired,
    PairingCodeInvalid,
)
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.secrets import Sha256Hasher
from dojo.model import AuditEvent, PairingCodeIssued, PairingResult
from dojo.pairing import CODE_TTL, IDLE_TTL
from dojo.testing import FIXED_AT


class MutableClock:
    def __init__(self, now: datetime = FIXED_AT) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def make_pairing() -> tuple[DojoPairing, InMemoryStore, MutableClock]:
    store = InMemoryStore()
    clock = MutableClock()
    pairing = DojoPairing(pairing=store, audit=store, clock=clock)
    return pairing, store, clock


def test_create_code_returns_raw_and_expiry() -> None:
    pairing, store, _ = make_pairing()
    issued = pairing.create_pairing_code(requester="cli")
    assert isinstance(issued, PairingCodeIssued)
    assert len(issued.raw_code) == 8
    assert issued.expires_at - FIXED_AT == CODE_TTL
    events = [e for e in store.list_recent() if e.action == "pairing.code_created"]
    assert len(events) == 1
    assert events[0].actor == "cli"


def test_pair_device_issues_authenticatable_token() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    assert isinstance(result, PairingResult)
    assert result.kind == "device"
    client = pairing.authenticate_bearer(result.raw_credential)
    assert client is not None
    assert client.name == "Phone"


def test_pair_browser_issues_session() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    client = pairing.authenticate_session(result.raw_credential)
    assert client is not None
    assert client.kind == "browser"


def test_code_is_single_use() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    pairing.validate_code(code=code, kind="device", name="Phone")
    with pytest.raises(PairingCodeConsumed):
        pairing.validate_code(code=code, kind="device", name="Other")


def test_code_expires() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    clock.advance(timedelta(minutes=11))
    with pytest.raises(PairingCodeExpired):
        pairing.validate_code(code=code, kind="device", name="Phone")


def test_unknown_code_rejected() -> None:
    pairing, _, _ = make_pairing()
    with pytest.raises(PairingCodeInvalid):
        pairing.validate_code(code="aaaaaaaa", kind="device", name="Phone")


def test_bad_kind_rejected_without_consuming() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    with pytest.raises(ValueError):
        pairing.validate_code(code=code, kind="laptop", name="Laptop")
    pairing.validate_code(code=code, kind="device", name="Phone")  # still usable


def test_pairing_audited_with_acting_client() -> None:
    pairing, store, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    pairing.validate_code(code=code, kind="device", name="Phone")
    paired: list[AuditEvent] = [
        e for e in store.list_recent() if e.action == "pairing.client_paired"
    ]
    assert len(paired) == 1
    assert paired[0].actor == "cli"
    assert paired[0].details["name"] == "Phone"
    assert paired[0].details["kind"] == "device"


def test_hashes_never_match_secrets() -> None:
    pairing, store, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    stored_codes = [c.code_hash for c in store._codes]  # noqa: SLF001
    stored_clients = list(store._client_hashes.values())  # noqa: SLF001
    assert code not in stored_codes
    assert result.raw_credential not in stored_clients
    assert Sha256Hasher().hash(code) in stored_codes


def test_revoke_denies_device() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    assert pairing.authenticate_bearer(result.raw_credential) is not None
    pairing.revoke_client(client_id=result.client_id, requester="cli")
    assert pairing.authenticate_bearer(result.raw_credential) is None


def test_revoke_denies_browser_session() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    assert pairing.authenticate_session(result.raw_credential) is not None
    pairing.revoke_client(client_id=result.client_id, requester="cli")
    assert pairing.authenticate_session(result.raw_credential) is None


def test_revoke_unknown_client_raises() -> None:
    pairing, _, _ = make_pairing()
    with pytest.raises(ClientNotFound):
        pairing.revoke_client(client_id=999, requester="cli")


def test_revoke_is_idempotent() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester="cli")
    pairing.revoke_client(client_id=result.client_id, requester="cli")


def test_revocation_audited_with_acting_client() -> None:
    pairing, store, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester="2")
    revoked = [e for e in store.list_recent() if e.action == "pairing.client_revoked"]
    assert len(revoked) == 1
    assert revoked[0].actor == "2"
    assert revoked[0].details["client_id"] == result.client_id


def test_browser_session_idle_expiry() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    clock.advance(IDLE_TTL)
    assert pairing.authenticate_session(result.raw_credential) is not None
    clock.advance(IDLE_TTL + timedelta(days=1))
    assert pairing.authenticate_session(result.raw_credential) is None


def test_activity_resets_idle_ttl() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    clock.advance(IDLE_TTL - timedelta(days=1))
    assert pairing.authenticate_session(result.raw_credential) is not None
    clock.advance(IDLE_TTL - timedelta(days=1))
    assert pairing.authenticate_session(result.raw_credential) is not None


def test_device_token_never_idle_expires() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    clock.advance(timedelta(days=400))
    assert pairing.authenticate_bearer(result.raw_credential) is not None


def test_list_clients_shows_revoked_flag() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    a = pairing.validate_code(code=code, kind="device", name="Phone")
    code = pairing.create_pairing_code(requester=str(a.client_id)).raw_code
    b = pairing.validate_code(code=code, kind="browser", name="Browser")
    pairing.revoke_client(client_id=a.client_id, requester=str(b.client_id))
    clients = {c.id: c for c in pairing.list_clients()}
    assert clients[a.client_id].revoked_at is not None
    assert clients[b.client_id].revoked_at is None


def test_equal_permissions_any_client_can_mint_and_revoke() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    a = pairing.validate_code(code=code, kind="device", name="A")
    code = pairing.create_pairing_code(requester=str(a.client_id)).raw_code
    b = pairing.validate_code(code=code, kind="device", name="B")
    pairing.revoke_client(client_id=b.client_id, requester=str(a.client_id))
    assert pairing.authenticate_bearer(b.raw_credential) is None


def test_single_use_under_concurrency(pg_store) -> None:
    import threading

    pairing = DojoPairing(pairing=pg_store, audit=pg_store)
    code = pairing.create_pairing_code(requester="cli").raw_code
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        try:
            barrier.wait(timeout=10)
            pairing.validate_code(code=code, kind="device", name="race")
            results.append("ok")
        except PairingCodeConsumed:
            results.append("consumed")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["consumed", "ok"]
