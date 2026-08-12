from __future__ import annotations

from dojo import DojoActivity, DojoPairing
from dojo.adapters.memory import InMemoryStore
from dojo.model import ActivityPage, AuditEvent, Client
from dojo.testing import FIXED_AT, FakeClock


def make_system() -> tuple[InMemoryStore, DojoPairing, DojoActivity]:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    activity = DojoActivity(audit=store, pairing=store)
    return store, pairing, activity


def test_newest_first_with_ids() -> None:
    store, pairing, activity = make_system()
    pairing.create_pairing_code(requester="cli")
    page = activity.list_activity()
    assert isinstance(page, ActivityPage)
    assert [e.action for e in page.entries] == ["pairing.code_created"]
    assert page.entries[0].id >= 1


def test_pairs_and_revokes_page_newest_first_no_overlap() -> None:
    store, pairing, activity = make_system()
    issued = pairing.create_pairing_code(requester="cli")
    result = pairing.validate_code(code=issued.raw_code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester=str(result.client_id))

    first = activity.list_activity(limit=1)
    assert first.next_cursor is not None
    second = activity.list_activity(limit=1, before_id=first.next_cursor)
    third = activity.list_activity(limit=1, before_id=second.next_cursor)

    ids = [e.id for e in first.entries + second.entries + third.entries]
    assert len(ids) == len(set(ids)) == 3
    assert all(a > b for a, b in zip(ids, ids[1:]))


def test_actor_resolved_to_revoked_client() -> None:
    store, pairing, activity = make_system()
    issued = pairing.create_pairing_code(requester="cli")
    result = pairing.validate_code(code=issued.raw_code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester=str(result.client_id))

    page = activity.list_activity()
    revoked = next(e for e in page.entries if e.action == "pairing.client_revoked")
    assert isinstance(revoked.actor, Client)
    assert revoked.actor.id == result.client_id
    assert revoked.actor.name == "Phone"
    assert revoked.actor.kind == "device"


def test_cli_actors_stay_literal() -> None:
    store, pairing, activity = make_system()
    pairing.create_pairing_code(requester="cli")
    page = activity.list_activity()
    assert all(e.actor == "cli" for e in page.entries)


def test_unknown_and_nonnumeric_actors_stay_literal() -> None:
    store, pairing, activity = make_system()
    store.append(AuditEvent(action="x", actor="999", occurred_at=FIXED_AT, details={}))
    store.append(AuditEvent(action="x", actor="not-a-client", occurred_at=FIXED_AT, details={}))
    actors = [e.actor for e in activity.list_activity().entries if e.action == "x"]
    assert actors == ["not-a-client", "999"]


def test_system_actor_stays_literal() -> None:
    store, pairing, activity = make_system()
    store.append(
        AuditEvent(action="package.created", actor="system", occurred_at=FIXED_AT, details={})
    )
    created = next(e for e in activity.list_activity().entries if e.action == "package.created")
    assert created.actor == "system"


def test_limit_clamped_to_100() -> None:
    store, pairing, activity = make_system()
    for _ in range(10):
        store.append(AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={}))
    assert len(activity.list_activity(limit=0).entries) == 1
    assert len(activity.list_activity(limit=999).entries) == 10


def test_next_cursor_null_when_page_partial() -> None:
    store, pairing, activity = make_system()
    store.append(AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={}))
    page = activity.list_activity(limit=50)
    assert len(page.entries) == 1
    assert page.next_cursor is None


def test_activity_over_postgres(pg_store) -> None:
    pairing = DojoPairing(pairing=pg_store, audit=pg_store, clock=FakeClock())
    activity = DojoActivity(audit=pg_store, pairing=pg_store)

    issued = pairing.create_pairing_code(requester="cli")
    result = pairing.validate_code(code=issued.raw_code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester=str(result.client_id))

    first = activity.list_activity(limit=1)
    assert first.next_cursor is not None
    assert first.entries[0].action == "pairing.client_revoked"
    second = activity.list_activity(limit=1, before_id=first.next_cursor)
    assert second.entries[0].action == "pairing.client_paired"