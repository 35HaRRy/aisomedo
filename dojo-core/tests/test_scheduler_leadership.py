from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import AuditEvent, Job, YayinZamani
from dojo.testing import FIXED_AT
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def observer(pg_store: PostgresStore) -> Iterator[PostgresStore]:
    other = PostgresStore(pg_store._engine.url.render_as_string(hide_password=False))
    try:
        yield other
    finally:
        other.dispose()


def emit(store: PostgresStore) -> None:
    store.create(YayinZamani(0, "regular", FIXED_AT, "pending", FIXED_AT))
    store.create(Job(0, "render-1", None, "render", "queued", {}, FIXED_AT))
    store.append(AuditEvent(action="render.queued", actor="system", occurred_at=FIXED_AT))


def counts(store: PostgresStore) -> tuple[int, ...]:
    with store._engine.connect() as conn:
        return tuple(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                     for table in ("yayin_zamani", "jobs", "audit_events"))


def test_second_worker_skips_emission_while_leader_holds_lock(
    pg_store: PostgresStore, observer: PostgresStore,
) -> None:
    from dojo.scheduler import try_emission_leadership

    barrier = Barrier(2, timeout=10)

    def follower() -> None:
        barrier.wait()
        with try_emission_leadership(observer) as leader:
            if leader:
                emit(observer)
            assert leader is False
        assert counts(observer) == (0, 0, 0)
        barrier.wait()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(follower)
        with try_emission_leadership(pg_store) as leader:
            assert leader is True
            emit(pg_store)
            assert len(pg_store.list_all()) == 1
            assert len(pg_store.list_recent()) == 1
            barrier.wait()
            barrier.wait()
        pending.result(timeout=10)
    assert counts(observer) == (1, 1, 1)
    with try_emission_leadership(observer) as leader:
        assert leader is True


def test_exception_in_emission_rolls_back_and_retries_next_tick(
    pg_store: PostgresStore, observer: PostgresStore,
) -> None:
    from dojo.scheduler import try_emission_leadership

    with pytest.raises(ValueError, match="injected"):
        with try_emission_leadership(pg_store):
            emit(pg_store)
            raise ValueError("injected")
    assert counts(observer) == (0, 0, 0)
    with try_emission_leadership(pg_store) as leader:
        assert leader is True
        emit(pg_store)
    assert counts(observer) == (1, 1, 1)


def test_lock_holder_termination_allows_takeover(
    pg_store: PostgresStore, observer: PostgresStore,
) -> None:
    from dojo.scheduler import try_emission_leadership

    barrier = Barrier(2, timeout=10)

    def terminate_and_take_over() -> None:
        barrier.wait()
        with observer._engine.begin() as conn:
            pid = conn.execute(text(
                "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted"
            )).scalar_one()
            assert conn.execute(text("SELECT pg_terminate_backend(:pid, 5000)"),
                                {"pid": pid}).scalar_one()
        assert counts(observer) == (0, 0, 0)
        with try_emission_leadership(observer) as leader:
            assert leader is True
            emit(observer)
        barrier.wait()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(terminate_and_take_over)
        with pytest.raises(DBAPIError):
            with try_emission_leadership(pg_store):
                emit(pg_store)
                barrier.wait()
                barrier.wait()
                # The former leader must fail, never silently open a fresh connection.
                pg_store.append(AuditEvent(action="stale", actor="system", occurred_at=FIXED_AT))
        pending.result(timeout=10)
    assert counts(observer) == (1, 1, 1)
    with try_emission_leadership(pg_store) as leader:
        assert leader is True
        pg_store.append(AuditEvent(action="recovered", actor="system", occurred_at=FIXED_AT))
    assert counts(observer) == (1, 1, 2)


def test_same_store_threads_use_independent_transactions(pg_store: PostgresStore) -> None:
    from dojo.scheduler import try_emission_leadership

    barrier = Barrier(2, timeout=10)

    def other_thread() -> None:
        barrier.wait()
        with try_emission_leadership(pg_store) as leader:
            assert leader is False
        # Standalone writes on this thread must survive the leader's rollback.
        pg_store.append(AuditEvent(action="other", actor="system", occurred_at=FIXED_AT))
        barrier.wait()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(other_thread)
        with pytest.raises(ValueError, match="rollback"):
            with try_emission_leadership(pg_store):
                emit(pg_store)
                barrier.wait()
                barrier.wait()
                raise ValueError("rollback")
        pending.result(timeout=10)
    assert counts(pg_store) == (0, 0, 1)
    assert pg_store.list_recent()[0].action == "other"


@pytest.mark.parametrize("fail", [False, True])
def test_method_commits_and_pruning_join_outer_transaction(
    pg_store: PostgresStore, observer: PostgresStore, fail: bool,
) -> None:
    from dojo.scheduler import try_emission_leadership

    future = pg_store.create(YayinZamani(
        0, "regular", FIXED_AT + timedelta(days=1), "pending", FIXED_AT,
    ))
    due = pg_store.create(YayinZamani(0, "manual", FIXED_AT, "pending", FIXED_AT))
    try:
        with try_emission_leadership(pg_store):
            assert pg_store.prune_regular_future(FIXED_AT) == 1
            updated = pg_store.update(replace(due, status="resolved"))
            assert updated.status == "resolved"
            assert pg_store.list_all() == [updated]
            pg_store.set("turn", {"ok": True}, updated_at=FIXED_AT)
            assert pg_store.get("turn") == {"ok": True}
            assert observer.list_all() == [future, due]
            assert observer.get("turn") is None
            if fail:
                raise ValueError("rollback")
    except ValueError:
        if not fail:
            raise
    assert observer.list_all() == ([future, due] if fail else [updated])
    assert observer.get("turn") == (None if fail else {"ok": True})


@pytest.mark.parametrize("memory", [False, True])
def test_nested_scopes_rejected_without_releasing_outer_leadership(
    pg_store: PostgresStore, observer: PostgresStore, memory: bool,
) -> None:
    from dojo.scheduler import try_emission_leadership

    store = InMemoryStore() if memory else pg_store
    with try_emission_leadership(store) as leader:
        assert leader is True
        with pytest.raises(RuntimeError, match="nested"):
            with try_emission_leadership(store):
                pytest.fail("nested scope accepted")
        if not memory:
            with try_emission_leadership(observer) as follower:
                assert follower is False
    with try_emission_leadership(store) as leader:
        assert leader is True


def test_advisory_lock_requires_explicit_transaction(pg_store: PostgresStore) -> None:
    with pytest.raises(RuntimeError, match="transaction"):
        pg_store.try_advisory_xact_lock(123)
