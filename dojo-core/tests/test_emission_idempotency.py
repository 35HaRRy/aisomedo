from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, time
from threading import Barrier, Event

import pytest
from dojo import DojoPublishing, SchedulePlan
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.stubs import StubReelRenderer
from dojo.model import AuditEvent, Job, YayinIncelemesi, YayinZamani
from dojo.testing import FIXED_AT, FakeClock
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .test_render import finalize_media


def seam(store, root, renderer=None):
    return DojoPublishing(
        packages=store, audit=store, jobs=store, uploads=store, settings=store,
        schedule=store, reviews=store, media_root=root, clock=FakeClock(),
        renderer=renderer or StubReelRenderer(),
    )


def job(name):
    return Job(id=0, job_id=name, upload_id=None, kind="render", status="queued",
               payload={"package": "p", "digest": "d"}, created_at=FIXED_AT)


def audit(action="render.queued"):
    return AuditEvent(action=action, actor="system", occurred_at=FIXED_AT, details={})


@pytest.fixture
def other(pg_store):
    store = PostgresStore(pg_store._engine.url.render_as_string(hide_password=False))
    yield store
    store.dispose()


@pytest.mark.parametrize("memory", [False, True])
def test_regular_identity_preserves_oneoffs(pg_store, memory):
    store = InMemoryStore() if memory else pg_store
    occ = YayinZamani(id=0, kind="regular", due_at=FIXED_AT,
                      status="pending", created_at=FIXED_AT)
    first = store.create(occ)
    assert store.create(occ).id == first.id
    oneoff = store.create(replace(occ, kind="oneoff"))
    assert store.create(replace(occ, kind="oneoff")).id != oneoff.id
    assert len(store.list_all()) == 3


def test_api_scheduler_race_creates_one_job_and_audit(pg_store, other, tmp_path):
    api, scheduler = seam(pg_store, tmp_path), seam(other, tmp_path)
    pg_store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    finalize_media(tmp_path, api)
    gate = Barrier(2)

    def request():
        gate.wait(timeout=10)
        api.render_preview()

    def tick():
        gate.wait(timeout=10)
        with other.emission_transaction():
            scheduler.evaluate_due_work()

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(request), pool.submit(tick)]
        for future in futures:
            future.result(timeout=20)
    assert len([e for e in pg_store.list_recent() if e.action == "render.queued"]) == 1
    assert api.claim_next_job().kind == "render"
    assert api.claim_next_job() is None


def test_later_tick_during_blocked_render(pg_store, other, tmp_path):
    entered, release = Event(), Event()

    class BlockedRenderer(StubReelRenderer):
        def render(self, build, work_dir, out_path):
            entered.set()
            assert release.wait(10)
            return super().render(build, work_dir, out_path)

    first = seam(pg_store, tmp_path, BlockedRenderer())
    second = seam(other, tmp_path)
    pg_store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    finalize_media(tmp_path, first)
    first.evaluate_due_work()
    claimed = first.claim_next_job()
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(first.process_job, claimed.job_id)
        try:
            assert entered.wait(10)
            with other.emission_transaction():
                second.evaluate_due_work()
            assert second.claim_next_job() is None
        finally:
            release.set()
        running.result(timeout=10)
    assert len([e for e in pg_store.list_recent() if e.action == "render.queued"]) == 1


def test_review_race_records_one_creation(pg_store, other, tmp_path, monkeypatch):
    first, second = seam(pg_store, tmp_path), seam(other, tmp_path)
    first.set_plan(SchedulePlan(
        anchor_date=date(2026, 8, 3), anchor_time=time(10), enabled=True,
    ))
    package = first.get_or_create_active_package()
    pg_store.create(YayinZamani(id=0, kind="regular", due_at=FIXED_AT,
                               status="pending", created_at=FIXED_AT))
    barrier = Barrier(2)
    # Force both legacy check-then-insert callers to observe absence.
    for store in (pg_store, other):
        original = store.get_by_occurrence_revision

        def checked(*args, lookup=original):
            result = lookup(*args)
            barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(store, "get_by_occurrence_revision", checked)

    def create(publishing, store):
        with store.emission_transaction():
            publishing._create_review_if_due(package, "d")
            store.append(audit("turn.completed"))

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(create, first, pg_store), pool.submit(create, second, other)]
        for future in futures:
            future.result(timeout=20)
    assert len(pg_store.list_pending()) == 1
    events = pg_store.list_recent()
    assert len([e for e in events if e.action == "review.created"]) == 1
    assert len([e for e in events if e.action == "turn.completed"]) == 2
    event = next(e for e in events if e.action == "review.created")
    assert event.details["review_id"] == pg_store.list_pending()[0].id


@pytest.mark.parametrize("memory", [False, True])
@pytest.mark.parametrize("terminal", ["failed", "completed"])
def test_created_contract_allows_terminal_retry(pg_store, memory, terminal):
    store = InMemoryStore() if memory else pg_store
    first, created = store.create_job_once(job("first"), audit=audit())
    assert created
    existing, created = store.create_job_once(job("duplicate"), audit=audit())
    assert not created and existing.id == first.id
    claimed = store.claim_next(FIXED_AT)
    assert store.create_job_once(job("blocked"), audit=audit()) == (claimed, False)
    store.update(replace(claimed, status=terminal, finished_at=FIXED_AT))
    retried, created = store.create_job_once(job("retry"), audit=audit())
    assert created and retried.id != first.id
    assert len(store.list_recent()) == 2


@pytest.mark.parametrize("outer", [False, True])
def test_audit_failure_rolls_back_job(pg_store, outer):
    from contextlib import nullcontext

    bad = replace(audit(), actor="x" * 65)
    with pytest.raises(Exception, match="value too long"):
        with pg_store.emission_transaction() if outer else nullcontext():
            pg_store.create_job_once(job("rollback"), audit=bad)
    assert pg_store.get("rollback") is None
    assert pg_store.list_recent() == []


def test_database_constraints_protect_direct_writers(pg_store):
    pg_store.create(job("first"))
    with pytest.raises(IntegrityError):
        with pg_store._engine.begin() as conn:
            conn.execute(text("""INSERT INTO jobs
                (job_id, kind, status, payload, created_at)
                VALUES ('bypass', 'render', 'processing',
                        '{"package":"p","digest":"d"}', now())"""))


def test_regular_occurrence_race_keeps_outer_transactions(pg_store, other):
    barrier = Barrier(2)
    occurrence = YayinZamani(id=0, kind="regular", due_at=FIXED_AT,
                            status="pending", created_at=FIXED_AT)

    def create(store):
        with store.emission_transaction():
            barrier.wait(timeout=10)
            created = store.create(occurrence)
            store.append(audit("turn.completed"))
            return created.id

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(create, store) for store in (pg_store, other)]
        ids = [future.result(timeout=20) for future in futures]
    assert ids[0] == ids[1]
    assert len(pg_store.list_all()) == 1
    assert len(pg_store.list_recent()) == 2


@pytest.mark.parametrize("memory", [False, True])
def test_review_insert_contract_and_revision_identity(pg_store, memory):
    store = InMemoryStore() if memory else pg_store
    review = YayinIncelemesi(id=0, occurrence_id=1, package_folder="p",
                            revision_digest="d", caption=None, status="pending",
                            created_at=FIXED_AT)
    first, created = store.create_review_once(review, audit=audit("review.created"))
    assert created
    assert store.create_review_once(review, audit=audit()) == (first, False)
    different, created = store.create_review_once(replace(review, revision_digest="d2"))
    assert created and different.id != first.id
    assert len(store.list_recent()) == 1
    assert store.list_recent()[0].details["review_id"] == first.id


def test_review_audit_failure_rolls_back_review(pg_store):
    review = YayinIncelemesi(id=0, occurrence_id=1, package_folder="p",
                            revision_digest="d", caption=None, status="pending",
                            created_at=FIXED_AT)
    with pytest.raises(Exception, match="value too long"):
        pg_store.create_review_once(review, audit=replace(audit(), actor="x" * 65))
    assert pg_store.list_pending() == []


def test_render_identity_includes_both_package_and_digest(pg_store):
    first = pg_store.create(job("first"))
    second = pg_store.create(replace(job("second"), payload={"package": "p2", "digest": "d"}))
    third = pg_store.create(replace(job("third"), payload={"package": "p", "digest": "d2"}))
    assert len({first.id, second.id, third.id}) == 3


@pytest.mark.parametrize("terminal", ["failed", "completed"])
def test_explicit_preview_retry(pg_store, tmp_path, terminal):
    renderer = StubReelRenderer()
    publishing = seam(pg_store, tmp_path, renderer)
    pg_store.set("branding.logo_asset", "logo.png", updated_at=FIXED_AT)
    finalize_media(tmp_path, publishing)
    publishing.render_preview()
    claimed = publishing.claim_next_job()
    if terminal == "failed":
        renderer.fail_reason = "failure"
    publishing.process_job(claimed.job_id)
    publishing.render_if_stale()
    assert publishing.claim_next_job() is None
    publishing.render_preview(retry=True)
    retry = publishing.claim_next_job()
    assert retry is not None and retry.id != claimed.id
    assert retry.payload == claimed.payload


@pytest.mark.parametrize("memory", [False, True])
def test_legacy_create_raises_on_duplicates(pg_store, memory):
    store = InMemoryStore() if memory else pg_store
    store.create(job("dup"))
    with pytest.raises(Exception):
        store.create(job("dup"))
    occ = store.create(YayinZamani(id=0, kind="regular", due_at=FIXED_AT,
                                   status="pending", created_at=FIXED_AT))
    review = YayinIncelemesi(id=0, occurrence_id=occ.id, package_folder="p",
                             revision_digest="d", caption=None, status="pending",
                             created_at=FIXED_AT)
    store.create(review)
    with pytest.raises(Exception):
        store.create(review)
