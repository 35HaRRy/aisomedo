from __future__ import annotations

from dojo import DojoPublishing, InMemoryStore
from worker.main import run_tick


class SpyPublishing(DojoPublishing):
    def __init__(self) -> None:
        self.ticks = 0
        super().__init__(
            packages=InMemoryStore(),
            audit=InMemoryStore(),
            media_root="/tmp/dojo-media",
        )

    def evaluate_due_work(self) -> None:
        self.ticks += 1


def test_run_tick_calls_evaluate_due_work() -> None:
    spy = SpyPublishing()
    run_tick(spy)
    assert spy.ticks == 1
