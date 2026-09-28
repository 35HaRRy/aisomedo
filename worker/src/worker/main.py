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
    kwargs: dict = {}
    notifier = _build_notifier()
    if notifier is not None:
        kwargs["notifier"] = notifier
    try:
        from dojo.adapters.meta import FernetCipher, HttpMetaPublisher

        key = os.environ.get("META_TOKEN_ENCRYPTION_KEY", "")
        if key:
            kwargs["meta"] = HttpMetaPublisher(
                connection_store=store,
                cipher=FernetCipher(key),
                graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
            )
    except Exception:  # noqa: BLE001
        logger.warning("meta publisher not configured; using stub")
    try:
        from dojo.adapters.signed_urls import HmacSignedUrlStore

        secret = os.environ.get("SIGNED_URL_SECRET", "")
        if secret:
            kwargs["signed_urls"] = HmacSignedUrlStore(
                base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000"),
                secret=secret,
            )
    except Exception:  # noqa: BLE001
        logger.warning("signed URL store not configured; using stub")
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=media_root,
        **kwargs,
    )
    try:
        publishing.repair_open_folders(requester="system")
    except Exception:  # noqa: BLE001 - startup repair never blocks boot
        logger.exception("open-folder repair failed")
    return publishing


def build_meta() -> object | None:
    try:
        from dojo.adapters.meta import (
            FernetCipher,
            HttpInstagramTokenProvider,
            StubMetaOAuthProvider,
        )
        from dojo.meta_connection import DojoMetaConnection

        url = os.environ.get("DATABASE_URL", "postgresql+psycopg://dojo:dojo@localhost:5432/dojo")
        store = PostgresStore(url)
        store.create_all()
        key = os.environ.get("META_TOKEN_ENCRYPTION_KEY", "")
        if not key:
            raise RuntimeError("META_TOKEN_ENCRYPTION_KEY is required")
        cipher = FernetCipher(key)
        provider = StubMetaOAuthProvider()
        return DojoMetaConnection(
            store=store,
            provider=provider,
            instagram_provider=HttpInstagramTokenProvider(
                graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
            ),
            cipher=cipher,
            audit=store,
            app_id=os.environ.get("META_APP_ID", "dev_app_id"),
            app_secret=os.environ.get("META_APP_SECRET", "dev_secret"),
            redirect_uri=os.environ.get("META_REDIRECT_URI", "http://localhost:8000/api/meta/oauth/callback"),
            graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
            allowed_return_uris=[u.strip() for u in os.environ.get("META_ALLOWED_RETURN_URIS", "").split(",") if u.strip()],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta connection not configured: %s", exc)
        return None


def run_tick(publishing: DojoPublishing, meta: object | None = None) -> None:
    if meta is not None:
        try:
            meta.maintain()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logger.exception("meta maintain failed")
    publishing.evaluate_due_work()
    try:
        publishing.reconcile_publication()
    except Exception:  # noqa: BLE001
        logger.exception("reconcile_publication failed")
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
    meta = build_meta()
    interval = float(os.environ.get("WORKER_INTERVAL_SECONDS", "10"))

    running = True

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while running:
        run_tick(publishing, meta)
        time.sleep(interval)

    logger.info("worker stopped")


if __name__ == "__main__":
    main()
