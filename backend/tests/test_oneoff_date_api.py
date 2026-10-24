from dataclasses import replace
from datetime import timedelta

import pytest
from dojo import YayinZamani
from dojo.testing import FIXED_AT
from test_dashboard_api import paired


def change(client, occurrence, due):
    return client.patch(f"/api/dashboard/occurrences/{occurrence.id}", json={
        "expected_due_at": occurrence.due_at.isoformat(), "new_due_at": due.isoformat(),
    })


@pytest.mark.parametrize("with_regular", [False, True])
def test_changes_future_oneoff_in_place_and_refreshes_dashboard(tmp_path, with_regular):
    client, publishing, _, _ = paired(tmp_path)
    store = publishing._schedule
    if with_regular:
        store.create(YayinZamani(0, "regular", FIXED_AT + timedelta(days=4), "pending", FIXED_AT))
    slot = store.create(YayinZamani(0, "oneoff", FIXED_AT + timedelta(days=1), "pending", FIXED_AT))
    due = FIXED_AT + timedelta(days=2 if with_regular else 100)
    before_version = client.get("/api/dashboard").headers["x-resource-version"]
    response = change(client, slot, due)
    assert response.status_code == 200
    assert response.json() == {
        "kind": "oneoff", "due_at": due.isoformat(), "occurrence_id": slot.id,
    }
    assert next(o for o in store.list_all() if o.id == slot.id) == replace(slot, due_at=due)
    refreshed = client.get("/api/dashboard")
    assert int(refreshed.headers["x-resource-version"]) > int(before_version)
    assert response.json() in refreshed.json()["next_slots"]
    assert len(store.list_all()) == (2 if with_regular else 1)
    assert any(e.action == "occurrence.date_changed" for e in publishing.list_audit())


@pytest.mark.parametrize("days", [-1, 0, 4, 5])
def test_rejects_invalid_date_without_writes(tmp_path, days):
    client, publishing, _, _ = paired(tmp_path)
    store = publishing._schedule
    store.create(YayinZamani(0, "regular", FIXED_AT + timedelta(days=4), "pending", FIXED_AT))
    slot = store.create(YayinZamani(0, "oneoff", FIXED_AT + timedelta(days=1), "pending", FIXED_AT))
    before = store.list_all(), publishing.list_audit()
    assert change(client, slot, FIXED_AT + timedelta(days=days)).status_code == 400
    assert (store.list_all(), publishing.list_audit()) == before


@pytest.mark.parametrize("kind,status,days", [
    ("regular", "pending", 1), ("manual", "pending", 1),
    ("oneoff", "resolved", 1), ("oneoff", "due", 1),
    ("oneoff", "pending", 0), ("oneoff", "pending", -1),
])
def test_only_future_pending_oneoff_is_editable(tmp_path, kind, status, days):
    client, publishing, _, _ = paired(tmp_path)
    slot = publishing._schedule.create(YayinZamani(
        0, kind, FIXED_AT + timedelta(days=days), status, FIXED_AT,
    ))
    before = publishing._schedule.list_all(), publishing.list_audit()
    assert change(client, slot, FIXED_AT + timedelta(days=2)).status_code == 409
    assert (publishing._schedule.list_all(), publishing.list_audit()) == before


def test_stale_date_does_not_overwrite_another_edit(tmp_path):
    client, publishing, _, _ = paired(tmp_path)
    slot = publishing._schedule.create(YayinZamani(
        0, "oneoff", FIXED_AT + timedelta(days=1), "pending", FIXED_AT,
    ))
    assert change(client, slot, FIXED_AT + timedelta(days=2)).status_code == 200
    assert change(client, slot, FIXED_AT + timedelta(days=3)).status_code == 409
    assert publishing._schedule.list_all()[0].due_at == FIXED_AT + timedelta(days=2)


def test_missing_occurrence_and_unauthenticated_edit(tmp_path):
    client, _, pairing, client_id = paired(tmp_path)
    slot = YayinZamani(999, "oneoff", FIXED_AT + timedelta(days=1), "pending", FIXED_AT)
    assert change(client, slot, FIXED_AT + timedelta(days=2)).status_code == 404
    pairing.revoke_client(client_id=client_id, requester="cli")
    assert change(client, slot, FIXED_AT + timedelta(days=2)).status_code == 401
