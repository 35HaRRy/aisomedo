from dataclasses import replace
from datetime import timedelta

import pytest
from dojo import DojoPublishing
from dojo.adapters.stubs import StubNotifier
from dojo.model import Client
from dojo.testing import FakeClock

from tests.test_empty_occurrence import empty_context
from tests.test_review import claim_render, finalize_media, monday_dt, set_logo

KEY = "reminders.empty_occurrences"


def register(store, token="test-token"):
    client = store.create_client(Client(0, "Phone", "device", monday_dt(), "cli"), token)
    store.register_token(client.id, token, monday_dt())


def test_empty_reminder_is_durable_for_360_minutes_across_restart(tmp_path, pg_store):
    store, seam, folder, occ = empty_context(tmp_path, pg_store)
    register(store)
    seam.send_due_reminders()
    sent, tokens = seam._notifier.sent[0]
    assert tokens == ["test-token"]
    assert sent.data == {"type": "empty_package", "occurrence_id": str(occ.id),
                         "package_folder": folder}
    assert store.get(KEY) == {str(occ.id): {
        "package_folder": folder, "last_reminded_at": monday_dt().isoformat(),
    }}
    restarted = DojoPublishing(packages=store, audit=store, settings=store,
                               media_root=tmp_path, clock=FakeClock(monday_dt()))
    restarted._clock = FakeClock(monday_dt() + timedelta(minutes=359))
    restarted.send_due_reminders()
    assert restarted._notifier.sent == []
    restarted._clock = FakeClock(monday_dt() + timedelta(minutes=360))
    restarted.send_due_reminders()
    assert len(restarted._notifier.sent) == 1


def test_empty_reminder_honors_08_inclusive_22_exclusive(tmp_path):
    store, seam, _, occ = empty_context(tmp_path)
    store.update(replace(occ, due_at=monday_dt().replace(hour=7)))
    register(store)
    for hour, minute, expected in [(7, 59, 0), (8, 0, 1), (14, 0, 2), (22, 0, 2)]:
        seam._clock = FakeClock(monday_dt().replace(hour=hour, minute=minute))
        seam.send_due_reminders()
        assert len(seam._notifier.sent) == expected


def test_no_registered_devices_does_not_advance_empty_cadence(tmp_path):
    store, seam, _, _ = empty_context(tmp_path)
    seam.send_due_reminders()
    assert seam._notifier.sent == []
    assert not store.get(KEY)
    register(store)
    seam.send_due_reminders()
    assert len(seam._notifier.sent) == 1


def test_whole_call_failure_does_not_advance_empty_cadence(tmp_path):
    store, seam, _, _ = empty_context(tmp_path)
    register(store)
    seam._notifier.fail_next = OSError("provider unreachable")
    seam.send_due_reminders()
    assert not store.get(KEY)
    assert seam.list_audit()[0].action == "notification.failed"
    seam.send_due_reminders()
    assert len(seam._notifier.sent) == 1
    assert seam.list_audit()[0].details["delivered"] == 1


def test_invalid_token_removed_and_transient_batch_keeps_existing_cadence_semantics(tmp_path):
    store, seam, _, _ = empty_context(tmp_path)
    register(store, "gone")
    register(store, "later")
    seam._notifier.invalid_tokens.add("gone")
    seam._notifier.transient_tokens.add("later")
    seam.send_due_reminders()
    assert [r.token for r in store.list_active_device_tokens()] == ["later"]
    assert store.get(KEY)
    seam.send_due_reminders()
    assert len(seam._notifier.sent) == 1
    assert seam.list_audit()[0].details["transient"] == 1


@pytest.mark.parametrize("corrupt", [
    [], {"obsolete": {}}, {"1": []},
    {"1": {"package_folder": "old", "last_reminded_at": monday_dt().isoformat()}},
    {"1": {"package_folder": "{folder}", "last_reminded_at": "bad"}},
    {"1": {"package_folder": "{folder}", "last_reminded_at": "2026-08-03T10:00:00"}},
    {"1": {"package_folder": "{folder}", "last_reminded_at": "2099-01-01T10:00:00+03:00"}},
])
def test_corrupt_empty_cadence_cannot_suppress_valid_reminder(tmp_path, corrupt):
    store, seam, folder, occ = empty_context(tmp_path)
    if isinstance(corrupt, dict) and isinstance(corrupt.get("1"), dict):
        corrupt = {"1": {**corrupt["1"], "package_folder": (
            folder if corrupt["1"].get("package_folder") == "{folder}" else "old"
        )}}
    store.set(KEY, corrupt, updated_at=monday_dt())
    register(store)
    seam.send_due_reminders()
    assert len(seam._notifier.sent) == 1
    assert store.get(KEY) == {str(occ.id): {
        "package_folder": folder, "last_reminded_at": monday_dt().isoformat(),
    }}


def test_each_due_empty_occurrence_gets_its_own_reminder(tmp_path):
    store, seam, _, occ = empty_context(tmp_path)
    manual = seam.manual_publish()
    register(store)
    seam.send_due_reminders()
    identities = [n.data["occurrence_id"] for n, _ in seam._notifier.sent]
    assert identities == [str(occ.id), str(manual.id)]
    assert set(store.get(KEY)) == {str(occ.id), str(manual.id)}


@pytest.mark.parametrize("change", ["skip", "reschedule", "finalize", "replace"])
def test_empty_cadence_pruned_when_context_changes_even_without_recipients(tmp_path, change):
    store, seam, folder, occ = empty_context(tmp_path)
    register(store)
    seam.send_due_reminders()
    assert store.get(KEY)
    if change == "skip":
        seam.skip_empty_occurrence(occ.id, folder, confirmed=True)
    elif change == "reschedule":
        seam.reschedule_empty_occurrence(occ.id, folder, monday_dt() + timedelta(days=1))
    elif change == "finalize":
        finalize_media(tmp_path, seam)
    else:
        store.update(replace(seam.get_active_package(), status="completed"))
    store.remove_by_token("test-token")
    seam._clock = FakeClock(monday_dt().replace(hour=23))
    seam.send_due_reminders()
    assert store.get(KEY) == {}
    assert len(seam._notifier.sent) == 1


def test_render_creates_same_occurrence_review_with_independent_reminder_cadence(tmp_path):
    store, seam, folder, occ = empty_context(tmp_path)
    register(store)
    seam.send_due_reminders()
    finalize_media(tmp_path, seam)
    set_logo(store, "logo.png")
    seam.evaluate_due_work()
    claim_render(seam)
    review = seam.list_pending_reviews()[0]
    assert (review.occurrence_id, review.package_folder) == (occ.id, folder)
    seam.send_due_reminders()
    assert [n.data["type"] for n, _ in seam._notifier.sent] == ["empty_package", "review_required"]
    assert seam._notifier.sent[1][0].data == {
        "type": "review_required", "review_id": str(review.id),
        "review_version": str(review.version), "package_folder": folder,
    }
    assert store.get(KEY) == {}
    seam.send_due_reminders()
    assert len(seam._notifier.sent) == 2


def test_empty_reminder_does_not_create_package_when_none_exists(tmp_path):
    store, seam, _, _ = empty_context(tmp_path)
    store.update(replace(seam.get_active_package(), status="completed"))
    seam._notifier = StubNotifier()
    register(store)
    seam.send_due_reminders()
    assert seam.get_active_package() is None
    assert seam._notifier.sent == []
