from __future__ import annotations

from datetime import datetime

from dojo import DojoPublishing, InMemoryStore, Job
from dojo.adapters.stubs import StubMediaProcessor
from worker.main import run_tick


class SpyPublishing(DojoPublishing):
    def __init__(self) -> None:
        self.ticks = 0
        self.processed_jobs: list[str] = []
        self.sweeps = 0
        self._claims_left = 1
        super().__init__(
            packages=InMemoryStore(),
            audit=InMemoryStore(),
            media_root="/tmp/dojo-media",
            media=StubMediaProcessor(),
        )

    def evaluate_due_work(self) -> None:
        self.ticks += 1

    def claim_next_job(self) -> Job | None:
        if self._claims_left:
            self._claims_left -= 1
            return Job(
                id=1,
                job_id="j-1",
                upload_id=1,
                kind="media",
                status="queued",
                payload={},
                created_at=datetime.now(),
            )
        return None

    def process_job(self, job_id: str) -> None:
        self.processed_jobs.append(job_id)

    def sweep_stale_uploads(self, ttl: object = None) -> int:
        self.sweeps += 1
        return 0


def test_run_tick_calls_evaluate_due_work() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    assert spy.ticks == 1


def test_run_tick_processes_claimed_job() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    assert spy.processed_jobs == ["j-1"]


def test_run_tick_sweeps_when_claims_exhausted() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    run_tick(spy)
    assert spy.processed_jobs == ["j-1"]
    assert spy.sweeps == 2


class RenderSpyPublishing(SpyPublishing):
    def claim_next_job(self) -> Job | None:
        return Job(
            id=2,
            job_id="r-1",
            upload_id=0,
            kind="render",
            status="queued",
            payload={"package": "pkg", "digest": "d-1"},
            created_at=datetime.now(),
        )


def test_run_tick_processes_render_job() -> None:
    spy = RenderSpyPublishing()
    run_tick(spy)
    assert spy.processed_jobs == ["r-1"]
