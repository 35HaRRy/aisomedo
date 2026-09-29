from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, time, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import AuditEvent, Job, SchedulePlan, YayinZamani
from dojo.testing import FIXED_AT, FakeClock
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker" / "src"))


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


MONDAY_ANCHOR = date(2026, 8, 3)


def _tick_publishing(store: PostgresStore, media_root: Path) -> DojoPublishing:
    return DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=media_root,
        clock=FakeClock(),
    )


def _finalize_one_photo(pub: DojoPublishing, package_folder: str) -> None:
    manifest_path = pub.media_root / package_folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["media"] = [{
        "media_id": "m1",
        "filename": "a.jpg",
        "content_type": "image/jpeg",
        "status": "finalized",
        "processed": {
            "path": "media/m1/processed.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 10,
        },
    }]
    manifest["order"] = ["m1"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _render_jobs(store: PostgresStore) -> list[tuple[str, str]]:
    with store._engine.connect() as conn:  # noqa: SLF001
        return [
            (str(job_id), str(status))
            for job_id, status in conn.execute(
                text("SELECT job_id, status FROM jobs WHERE kind = 'render' ORDER BY id")
            ).all()
        ]


def test_run_tick_follower_processes_job_but_emits_nothing(
    pg_store: PostgresStore, observer: PostgresStore, tmp_path: Path,
) -> None:
    from dojo.scheduler import try_emission_leadership
    from worker.main import run_tick

    media_root = tmp_path / "media"
    leader_pub = _tick_publishing(pg_store, media_root)
    package = leader_pub.ensure_active_package()
    leader_pub.set_plan(SchedulePlan(
        anchor_date=MONDAY_ANCHOR, anchor_time=time(9, 0), enabled=True,
    ))
    pg_store.create(Job(
        0, "seed-render", None, "render", "queued",
        {"package": package.folder_name, "digest": "d1"}, FIXED_AT,
    ))
    follower_pub = _tick_publishing(observer, media_root)

    barrier = Barrier(2, timeout=15)

    def hold_leadership() -> None:
        with try_emission_leadership(pg_store) as leader:
            assert leader is True
            barrier.wait()
            barrier.wait()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(hold_leadership)
        barrier.wait()
        run_tick(follower_pub, None)
        barrier.wait()
        pending.result(timeout=15)

    assert observer.list_all() == []
    assert follower_pub.list_pending_reviews() == []
    assert observer.get("seed-render").status == "failed"
    assert _render_jobs(observer) == [("seed-render", "failed")]

    # The seeded setup really would emit: the leader tick materializes the plan.
    run_tick(leader_pub, None)
    assert len(observer.list_all()) == 2


def test_run_tick_slow_render_second_tick_enqueues_no_second_job(
    pg_store: PostgresStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worker.main import run_tick

    pub = _tick_publishing(pg_store, tmp_path / "media")
    package = pub.ensure_active_package()
    _finalize_one_photo(pub, package.folder_name)

    monkeypatch.setattr(pub, "claim_next_job", lambda: None)
    run_tick(pub, None)
    queued = _render_jobs(pg_store)
    assert len(queued) == 1
    assert queued[0][1] == "queued"

    # Slow renderer holds the first job across the next turn.
    monkeypatch.undo()
    claimed = pub.claim_next_job()
    assert claimed is not None and claimed.status == "processing"
    run_tick(pub, None)
    assert [status for _, status in _render_jobs(pg_store)] == ["processing"]

    # Once the slow render finishes, later ticks still add nothing.
    pub.process_job(claimed.job_id)
    run_tick(pub, None)
    assert len(_render_jobs(pg_store)) == 1


def test_run_tick_emission_exception_recovers_next_tick(
    pg_store: PostgresStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worker.main import run_tick

    pub = _tick_publishing(pg_store, tmp_path / "media")
    package = pub.ensure_active_package()
    _finalize_one_photo(pub, package.folder_name)
    pub.set_plan(SchedulePlan(
        anchor_date=MONDAY_ANCHOR, anchor_time=time(9, 0), enabled=True,
    ))

    def _boom(self: DojoPublishing, *args: object, **kwargs: object) -> None:
        raise RuntimeError("injected emission failure")

    monkeypatch.setattr(DojoPublishing, "_enqueue_render", _boom)
    run_tick(pub, None)
    assert pg_store.list_all() == []
    assert _render_jobs(pg_store) == []

    monkeypatch.undo()
    run_tick(pub, None)
    assert len(pg_store.list_all()) == 2
    assert len(_render_jobs(pg_store)) == 1
