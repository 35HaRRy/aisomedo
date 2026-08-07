from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore

logger = logging.getLogger(__name__)


def build_publishing() -> DojoPublishing:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"
    )
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(packages=store, audit=store, media_root=media_root)


def run_tick(publishing: DojoPublishing) -> None:
    publishing.evaluate_due_work()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    publishing = build_publishing()
    interval = float(os.environ.get("WORKER_INTERVAL_SECONDS", "10"))

    running = True

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while running:
        run_tick(publishing)
        time.sleep(interval)

    logger.info("worker stopped")


if __name__ == "__main__":
    main()
