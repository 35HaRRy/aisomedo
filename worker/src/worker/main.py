from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path

from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore
from dojo.scheduler import try_emission_leadership

logger = logging.getLogger(__name__)

#: Exact production-DDL contract: only the literal string "1" skips schema
#: creation. Unset or any other value keeps the current dev behavior
#: (create_all on boot). Production sets SKIP_CREATE_ALL=1 and lets the
#: initializer (`python -m dojo.schema`) own the schema instead.
SKIP_CREATE_ALL_VALUE = "1"


def _maybe_create_all(store: PostgresStore) -> None:
    """Create schema unless SKIP_CREATE_ALL=1 (initializer owns prod schema)."""
    if os.environ.get("SKIP_CREATE_ALL") == SKIP_CREATE_ALL_VALUE:
        logger.info("SKIP_CREATE_ALL=1; skipping create_all (initializer owns schema)")
        return
    store.create_all()


def _emission_store(publishing: DojoPublishing) -> object | None:
    """Return the shared store backing emission writes, if it coordinates.

    Production wires one PostgresStore through every DojoPublishing port, so
    ``_packages`` is that instance. The scan fallback keeps directly built
    publishing objects working without coupling run_tick to a new public API.
    """
    for attr in (
        "_packages", "_schedule", "_jobs", "_reviews",
        "_audit", "_uploads", "_settings",
    ):
        store = getattr(publishing, attr, None)
        if hasattr(store, "emission_transaction") and hasattr(
            store, "try_advisory_xact_lock"
        ):
            return store
    return None


def resolve_public_base_url() -> str:
    """Canonical public origin (mirrors backend.deps; worker has no backend dep)."""
    origin = os.environ.get("PUBLIC_HTTPS_ORIGIN", "").strip() or os.environ.get(
        "PUBLIC_BASE_URL", "http://localhost:8000"
    ).strip()
    return origin.rstrip("/") or "http://localhost:8000"


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
    _maybe_create_all(store)
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
                base_url=resolve_public_base_url(),
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
        _maybe_create_all(store)
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
            redirect_uri=os.environ.get("META_REDIRECT_URI", "").strip()
            or f"{resolve_public_base_url()}/api/meta/oauth/callback",
            graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
            allowed_return_uris=[u.strip() for u in os.environ.get("META_ALLOWED_RETURN_URIS", "").split(",") if u.strip()],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta connection not configured: %s", exc)
        return None


def _run_emission_turn(publishing: DojoPublishing) -> bool:
    """Schedule evaluation under per-turn advisory leadership.

    Only the lock holder emits; followers skip. The exception must propagate
    through ``try_emission_leadership`` so the turn rolls back — it is caught
    outside the scope and the next tick retries. Returns True for the leader.
    """
    store = _emission_store(publishing)
    if store is None:
        try:
            publishing.evaluate_due_work()
        except Exception:  # noqa: BLE001
            logger.exception("emission turn failed; will retry next tick")
        return False
    try:
        with try_emission_leadership(store) as leader:  # type: ignore[arg-type]
            if leader:
                publishing.evaluate_due_work()
            return leader
    except Exception:  # noqa: BLE001
        logger.exception("emission turn failed; will retry next tick")
        return False


def _run_singleton_turn(publishing: DojoPublishing, meta: object | None) -> None:
    """Leader-only follow-ups, each fault-isolated, outside the emission txn.

    Reconciliation polls saved Meta identifiers over HTTP, reminders send
    push, sweeps abort stale uploads, and meta.maintain refreshes tokens on
    its own separately constructed store — none of them may hold the emission
    transaction across those calls, and none may run concurrently on two
    workers merely because followers can claim jobs. Gating on the emission
    leader flag coordinates them as singletons without sharing transactions.
    """
    if meta is not None:
        try:
            meta.maintain()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logger.exception("meta maintain failed")
    try:
        publishing.reconcile_publication()
    except Exception:  # noqa: BLE001
        logger.exception("reconcile_publication failed")
    try:
        publishing.send_due_reminders()
    except Exception:  # noqa: BLE001
        logger.exception("send_due_reminders failed")
    try:
        publishing.sweep_stale_uploads()
    except Exception:  # noqa: BLE001
        logger.exception("sweep_stale_uploads failed")


def _run_job_turn(publishing: DojoPublishing) -> None:
    """Concurrent-safe job execution on every worker via atomic claims.

    ``claim_next_job`` uses SELECT ... FOR UPDATE SKIP LOCKED, so followers
    may process while the leader emits; render/HTTP work stays outside the
    emission transaction by construction (the scope already closed).
    """
    try:
        job = publishing.claim_next_job()
    except Exception:  # noqa: BLE001
        logger.exception("claim_next_job failed")
        return
    if job is not None:
        try:
            publishing.process_job(job.job_id)
        except Exception:  # noqa: BLE001
            logger.exception("process_job failed for job %s", job.job_id)


def run_tick(publishing: DojoPublishing, meta: object | None = None) -> None:
    """One scheduler turn: leadership-gated emission, leader singletons, jobs.

    Never raises: every operation is fault-isolated so an uncaught tick error
    cannot kill the worker; the main loop keeps the normal interval instead
    of tight-looping on DB-unavailable.
    """
    leader = _run_emission_turn(publishing)
    if leader:
        _run_singleton_turn(publishing, meta)
    _run_job_turn(publishing)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    publishing = build_publishing()
    meta = build_meta()
    interval = float(os.environ.get("WORKER_INTERVAL_SECONDS", "10"))

    stop = threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # SIGTERM sets the flag AND bounds in-flight work: the sleep is
    # interruptible (no new wait after stop), no new tick starts, and an
    # in-flight render runs at most until the container orchestrator's
    # stop_grace_period ends it (Task 4 owns that Compose value; this worker
    # assumes 120s — see the task-2 handoff report).
    while not stop.is_set():
        try:
            run_tick(publishing, meta)
        except Exception:  # noqa: BLE001 - belt and braces; run_tick is isolated
            logger.exception("worker tick failed; continuing")
        stop.wait(interval)

    logger.info("worker stopped")


if __name__ == "__main__":
    main()
