from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore

logger = logging.getLogger(__name__)


def _build_notifier() -> object | None:
    if os.environ.get("FCM_ENABLED", "false").lower() not in ("1", "true", "yes"):
        return None
    try:
        from dojo.adapters.fcm import FcmNotifier

        return FcmNotifier()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("FCM enabled but firebase_admin not configured") from exc


def build_publishing() -> DojoPublishing:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"
    )
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    notifier = _build_notifier()
    if notifier is not None:
        return DojoPublishing(packages=store, audit=store, media_root=media_root, notifier=notifier)  # type: ignore[arg-type]
    return DojoPublishing(packages=store, audit=store, media_root=media_root)


def run_tick(publishing: DojoPublishing) -> None:
    publishing.evaluate_due_work()
    job = publishing.claim_next_job()
    if job is not None:
        publishing.process_job(job.job_id)
    try:
        publishing.send_due_reminders()
    except Exception:  # noqa: BLE001
        logger.exception("send_due_reminders failed")
    publishing.sweep_stale_uploads()


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
