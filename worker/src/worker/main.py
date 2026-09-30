from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path

from dojo import DojoPublishing
from dojo.adapters.db import PostgresStore
from dojo.adapters.fcm import FcmNotifier
from dojo.observability import configure_logging
from dojo.scheduler import try_emission_leadership

from worker.health import DEFAULT_PATH as WORKER_HEALTH_DEFAULT_PATH
from worker.health import WorkerHealth

logger = logging.getLogger(__name__)

#: Exact production-DDL contract: only the literal string "1" skips schema
#: creation. Unset or any other value keeps the current dev behavior
#: (create_all on boot). Production sets SKIP_CREATE_ALL=1 and lets the
#: initializer (`python -m dojo.schema`) own the schema instead.
SKIP_CREATE_ALL_VALUE = "1"


def _maybe_create_all(store: PostgresStore) -> None:
    """Create schema unless SKIP_CREATE_ALL=1 (initializer owns prod schema)."""
    if os.environ.get("SKIP_CREATE_ALL") == SKIP_CREATE_ALL_VALUE:
        logger.info(
            "SKIP_CREATE_ALL=1; skipping create_all (initializer owns schema)",
            extra={"event": "schema.create_all_skipped"},
        )
        return
    store.create_all()


def _emission_store(publishing: DojoPublishing) -> object | None:
    """Return the shared store backing emission writes, if it coordinates.

    Production wires one PostgresStore through every DojoPublishing port, so
    ``_packages`` is that instance. The scan fallback keeps directly built
    publishing objects working without coupling run_tick to a new public API.

    Single-store expectation: production wires one PostgresStore through every
    port. When coordinator-capable ports are DISTINCT instances, leadership is
    elected on the returned store while emission may write through another —
    so log loudly (names + count) instead of silently picking first. Distinct
    per-port stores remain supported (dev/test pattern); the warning makes a
    production miswire visible rather than silent.

    Fallback contract: ``None`` (no coordinator-capable port) means emit
    directly without leadership gating. That path exists for directly built
    dev/test publishing objects only; production always wires a coordinating
    PostgresStore, so leadership always gates there.
    """
    attrs = (
        "_packages", "_schedule", "_jobs", "_reviews",
        "_audit", "_uploads", "_settings",
    )
    pairs: list[tuple[str, object]] = []
    for attr in attrs:
        store = getattr(publishing, attr, None)
        if hasattr(store, "emission_transaction") and hasattr(
            store, "try_advisory_xact_lock"
        ):
            pairs.append((attr, store))
    if not pairs:
        return None
    first_attr, first = pairs[0]
    others = sorted(attr for attr, store in pairs[1:] if store is not first)
    if others:
        logger.warning(
            "publishing ports do not share one emission store: "
            "%d distinct coordinator instances (first=%s, others=%s); "
            "leadership gates on the first",
            len({id(store) for _, store in pairs}),
            first_attr,
            ",".join(others),
            extra={"event": "emission.split_store", "status": first_attr},
        )
    return first


def resolve_public_base_url(cookie_secure: bool | None = None) -> str:
    """Canonical public origin (mirrors backend.deps; worker has no backend dep).

    Fail-closed on operator typo: non-localhost http origin raises while
    COOKIE_SECURE resolves true (default true); dev localhost exempt.
    """
    from urllib.parse import urlparse

    raw = os.environ.get("PUBLIC_HTTPS_ORIGIN", "").strip()
    origin = raw or os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").strip()
    origin = origin.rstrip("/") or "http://localhost:8000"
    secure = (
        cookie_secure
        if cookie_secure is not None
        else os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    )
    if secure:
        host = (urlparse(origin).hostname or "").lower()
        if urlparse(origin).scheme != "https" and host not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError(
                f"refusing non-https public origin {origin!r} while COOKIE_SECURE is true; "
                "fix PUBLIC_HTTPS_ORIGIN to an https:// URL (dev localhost exempt)"
            )
    return origin


#: Accepted ``FCM_ENABLED`` spellings; anything else leaves real delivery off.
FCM_ENABLED_VALUES = ("1", "true", "yes")


def build_notifier() -> FcmNotifier | None:
    """The real push notifier, or ``None`` when FCM is disabled.

    There is no stub fallback: a stub would report durable operational alerts
    as delivered without a provider, and a broken configuration must fail
    startup rather than silence them. Credentials and project identity are
    resolved by the adapter at construction.
    """
    if os.environ.get("FCM_ENABLED", "false").lower() not in FCM_ENABLED_VALUES:
        return None
    project_id = (
        os.environ.get("FCM_PROJECT_ID", "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or None
    )
    try:
        return FcmNotifier(project_id=project_id)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("FCM enabled but firebase_admin not configured") from exc


def build_publishing() -> DojoPublishing:
    resolve_public_base_url()  # fail fast on non-https origin while secure
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"
    )
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    _maybe_create_all(store)
    kwargs: dict = {}
    notifier = build_notifier()
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
        logger.warning(
            "meta publisher not configured; using stub",
            extra={"event": "publisher.stub_fallback", "status": "meta"},
        )
    try:
        from dojo.adapters.signed_urls import HmacSignedUrlStore

        secret = os.environ.get("SIGNED_URL_SECRET", "")
        if secret:
            kwargs["signed_urls"] = HmacSignedUrlStore(
                base_url=resolve_public_base_url(),
                secret=secret,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "signed URL store not configured; using stub",
            extra={"event": "publisher.stub_fallback", "status": "signed_urls"},
        )
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
        logger.exception(
            "open-folder repair failed",
            extra={"event": "startup.folder_repair_failed", "status": "error"},
        )
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
        logger.warning(
            "meta connection not configured: %s",
            exc,
            extra={"event": "startup.meta_unavailable"},
        )
        return None


def _run_emission_turn(publishing: DojoPublishing) -> bool:
    """Schedule evaluation under per-turn advisory leadership.

    Only the lock holder emits; followers skip. The exception must propagate
    through ``try_emission_leadership`` so the turn rolls back — it is caught
    outside the scope and the next tick retries. Returns True for the leader.
    """
    store = _emission_store(publishing)
    if store is None:
        # Fallback contract (see _emission_store): no coordinator means emit
        # directly; production never takes this path (PostgresStore always
        # coordinates), so this stays ungated by design, not by accident.
        try:
            publishing.evaluate_due_work()
        except Exception:  # noqa: BLE001
            logger.exception(
                "emission turn failed; will retry next tick",
                extra={"event": "emission.turn_failed", "status": "error"},
            )
        return False
    try:
        with try_emission_leadership(store) as leader:  # type: ignore[arg-type]
            if leader:
                publishing.evaluate_due_work()
            return leader
    except Exception:  # noqa: BLE001
        logger.exception(
            "emission turn failed; will retry next tick",
            extra={"event": "emission.turn_failed", "status": "error"},
        )
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
            logger.exception(
                "meta maintain failed",
                extra={"event": "singleton.meta_maintain_failed", "status": "error"},
            )
    for operation, call in (
        ("reconcile_publication", lambda: publishing.reconcile_publication()),
        ("send_due_reminders", lambda: publishing.send_due_reminders()),
        ("sweep_stale_uploads", lambda: publishing.sweep_stale_uploads()),
    ):
        try:
            call()
        except Exception:  # noqa: BLE001
            logger.exception(
                "%s failed", operation, extra={"event": f"singleton.{operation}_failed"}
            )


def _elapsed_ms(started: float) -> float:
    """Monotonic milliseconds, rounded so records stay compact."""
    return round((time.perf_counter() - started) * 1000, 3)


def _run_job_turn(publishing: DojoPublishing) -> None:
    """Concurrent-safe job execution on every worker via atomic claims.

    ``claim_next_job`` uses SELECT ... FOR UPDATE SKIP LOCKED, so followers
    may process while the leader emits; render/HTTP work stays outside the
    emission transaction by construction (the scope already closed).

    Job outcomes are logged with a stable ``job.outcome`` event carrying only
    the job id and status: ``process_job`` records expected failures itself, so
    this is the per-execution outcome, not the durable failure alert that
    monitoring derives from persisted state.
    """
    try:
        job = publishing.claim_next_job()
    except Exception:  # noqa: BLE001
        logger.exception(
            "claim_next_job failed", extra={"event": "job.claim_failed", "status": "error"}
        )
        return
    if job is None:
        return
    job_id = str(job.job_id)
    started = time.perf_counter()
    try:
        publishing.process_job(job.job_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "process_job raised",
            extra={
                "event": "job.outcome",
                "job_id": job_id,
                "status": "error",
                "duration_ms": _elapsed_ms(started),
            },
        )
        return
    logger.info(
        "job processed",
        extra={
            "event": "job.outcome",
            "job_id": job_id,
            "status": "processed",
            "duration_ms": _elapsed_ms(started),
        },
    )


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


def build_worker_health(interval_seconds: float) -> WorkerHealth:
    """Container-local health record wired to the tick loop.

    The idle deadline must exceed the tick interval, otherwise a healthy
    loop would look stale between turns.
    """
    path = Path(os.environ.get("WORKER_HEALTH_PATH", str(WORKER_HEALTH_DEFAULT_PATH)))
    idle_seconds = float(os.environ.get("WORKER_HEALTH_IDLE_SECONDS", "120"))
    busy_seconds = float(os.environ.get("WORKER_HEALTH_BUSY_SECONDS", "3600"))
    health = WorkerHealth(path, idle_seconds=idle_seconds, busy_seconds=busy_seconds)
    if idle_seconds <= interval_seconds:
        raise RuntimeError(
            f"WORKER_HEALTH_IDLE_SECONDS ({idle_seconds}) must exceed "
            f"WORKER_INTERVAL_SECONDS ({interval_seconds})"
        )
    return health


def _mark_health(write: Callable[[], None], phase: str) -> None:
    """Record a worker phase without ever failing the caller.

    Health is diagnostic: a full disk, a read-only ``/tmp`` or a bad
    permission must not stop publication and review processing, and a failed
    ``stopped()`` write in the shutdown ``finally`` must not mask an
    in-flight exception. Every failure is logged and the probe simply
    reports unhealthy, which is the truthful outcome.
    """
    try:
        write()
    except Exception:  # noqa: BLE001 - health writes are never load-bearing
        logger.warning(
            "worker health %s write failed; probe will report unhealthy",
            phase,
            exc_info=True,
            extra={"event": "worker.health_write_failed", "status": phase},
        )


def main() -> None:
    # Configured before any dependency construction so boot failures are
    # already structured JSON rather than the bare basicConfig format.
    configure_logging("worker")
    publishing = build_publishing()
    meta = build_meta()
    interval = float(os.environ.get("WORKER_INTERVAL_SECONDS", "10"))
    health = build_worker_health(interval)
    _mark_health(health.idle, "idle")

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
    logger.info("worker started", extra={"event": "service.startup"})
    try:
        while not stop.is_set():
            _mark_health(health.busy, "busy")
            try:
                run_tick(publishing, meta)
            except Exception:  # noqa: BLE001 - belt and braces; run_tick is isolated
                logger.exception(
                    "worker tick failed; continuing",
                    extra={"event": "worker.tick_failed", "status": "error"},
                )
            _mark_health(health.idle, "idle")
            stop.wait(interval)
    finally:
        _mark_health(health.stopped, "stopped")

    logger.info("worker stopped", extra={"event": "service.shutdown"})


if __name__ == "__main__":
    main()
