from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import psycopg
import pytest
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Package
from dojo.testing import FIXED_AT


@pytest.fixture(params=["memory", "postgres"])
def store(request, pg_store):
    return InMemoryStore() if request.param == "memory" else pg_store


@pytest.fixture
def package(store):
    return store.create(Package(id=0, folder_name="20261020", created_at=FIXED_AT,
                                status="active"))


@pytest.fixture
def other(pg_store):
    value = PostgresStore(pg_store._engine.url.render_as_string(hide_password=False))
    yield value
    value.dispose()


def test_state_and_event_rollback_together(store, package):
    with store.command_transaction():
        first = store.write_package_state(package.id, {"order": ["a"]}, content_changed=True)
        committed = store.record_change(["dashboard"])
    with pytest.raises(ValueError, match="reject"):
        with store.command_transaction():
            store.write_package_state(package.id, {"order": ["b"]}, content_changed=True)
            rejected = store.record_change(["dashboard"], revoked_client_ids=[7])
            raise ValueError("reject")
    assert store.read_package_state(package.id) == first
    assert store.get_change(rejected.event_id) is None
    assert store.get_change(committed.event_id).versions == {"dashboard": 2}
    assert store.get_resource_version("dashboard") == 2


def test_nested_commands_join_outer_rollback(store, package):
    with pytest.raises(ValueError, match="reject"):
        with store.emission_transaction():
            with store.command_transaction():
                store.write_package_state(package.id, {"order": ["a"]}, content_changed=True)
                event = store.record_change(["dashboard"])
            raise ValueError("reject")
    assert store.read_package_state(package.id) is None
    assert store.get_change(event.event_id) is None
    assert store.get_resource_version("dashboard") == 1


def test_memory_nested_command_rollback(package):
    store = InMemoryStore()
    package = store.create(package)
    with pytest.raises(ValueError, match="reject"):
        with store.command_transaction():
            with store.command_transaction():
                store.write_package_state(package.id, {"order": ["a"]}, content_changed=True)
                store.record_change(["dashboard"])
                raise ValueError("reject")
    assert store.read_package_state(package.id) is None
    assert store.get_resource_version("dashboard") == 1


def test_changes_are_not_visible_before_outer_commit(pg_store, other):
    package = pg_store.create(Package(id=0, folder_name="20261020", created_at=FIXED_AT,
                                      status="active"))
    with pg_store.emission_transaction():
        with pg_store.command_transaction():
            pg_store.write_package_state(package.id, {"order": []}, content_changed=True)
            event = pg_store.record_change(["dashboard"])
        assert other.read_package_state(package.id) is None
        assert other.get_change(event.event_id) is None
    assert other.read_package_state(package.id).document == {"order": []}
    assert other.get_change(event.event_id).versions == {"dashboard": 2}


def test_notify_after_commit_only(pg_store):
    url = pg_store._engine.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1,
    )
    with psycopg.connect(url, autocommit=True) as listener:
        listener.execute("LISTEN dojo_changes")
        with pg_store.command_transaction():
            event = pg_store.record_change(["dashboard"])
            assert list(listener.notifies(timeout=0.05)) == []
        notices = list(listener.notifies(timeout=1, stop_after=1))
        assert [(n.channel, n.payload) for n in notices] == [("dojo_changes", event.event_id)]
        with pytest.raises(ValueError):
            with pg_store.command_transaction():
                pg_store.record_change(["dashboard"])
                raise ValueError("rollback")
        assert list(listener.notifies(timeout=0.05)) == []


def test_state_revisions_and_copy_isolation(store, package):
    document = {"order": ["a"]}
    with store.command_transaction():
        first = store.write_package_state(package.id, document, content_changed=True)
    document["order"].append("do-not-save")
    assert first.document == {"order": ["a"]}
    first.document["order"].append("also-not-saved")
    with store.command_transaction():
        current = store.read_package_state(package.id, for_update=True)
        assert current.document == {"order": ["a"]}
        second = store.write_package_state(package.id, {"order": ["b"]}, content_changed=True)
    with store.command_transaction():
        third = store.write_package_state(package.id, {"order": ["b"], "status": "ready"},
                                         content_changed=False)
    assert (second.content_revision, second.view_revision) == (2, 2)
    assert (third.content_revision, third.view_revision) == (2, 3)


def test_events_deduplicate_resource_keys_and_copy_payloads(store):
    with store.command_transaction():
        event = store.record_change(["setup", "dashboard", "setup"], revoked_client_ids=[7])
    original = deepcopy(event)
    assert event.versions == {"dashboard": 1, "setup": 1}
    event.versions["dashboard"] = 999
    event.revoked_client_ids.append(8)
    assert store.get_change(original.event_id) == original
    with store.command_transaction():
        next_event = store.record_change(["dashboard"])
    assert next_event.versions == {"dashboard": 2}
    assert next_event.event_id != original.event_id
    assert store.get_resource_version("unknown") == 0


def test_mutations_and_locking_require_command_transaction(store, package):
    for operation in (
        lambda: store.write_package_state(package.id, {}, content_changed=True),
        lambda: store.record_change(["dashboard"]),
        lambda: store.read_package_state(package.id, for_update=True),
    ):
        with pytest.raises(RuntimeError, match="transaction"):
            operation()


def test_concurrent_resource_versions_are_serialized(pg_store, other):
    def change(store):
        with store.command_transaction():
            return store.record_change(["setup", "dashboard"])
    with ThreadPoolExecutor(2) as pool:
        events = list(pool.map(change, [pg_store, other]))
    assert sorted(e.versions["dashboard"] for e in events) == [1, 2]
    assert all(e.versions["dashboard"] == e.versions["setup"] for e in events)


def test_memory_rollback_restores_replaced_domain_values():
    store = InMemoryStore()
    before = store.upsert_active(
        ig_user_id="ig-1", ig_username="dojo", page_id=None, page_name=None,
        encrypted_token="encrypted", token_expires_at=FIXED_AT, health="healthy",
        last_checked_at=FIXED_AT, last_refreshed_at=None, last_error=None,
    )
    with pytest.raises(ValueError):
        with store.command_transaction():
            store.update_health("unhealthy", FIXED_AT, "rejected")
            raise ValueError("reject")
    assert store.get_meta_status() == before
