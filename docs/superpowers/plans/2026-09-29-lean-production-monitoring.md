# Lean Production Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #22: useful container health, safe structured logs, durable operational alerts through FCM, and verified hosted HTTPS monitoring.

**Architecture:** Extend the existing backend/worker deployment with small health and logging modules and a Dojo monitoring service. Persist incident transitions and per-recipient delivery attempts in PostgreSQL; never hold a transaction while calling FCM. A hosted monitor checks the public web and API independently of the VPS.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, SQLAlchemy 2/PostgreSQL 16, Alembic, Firebase Admin Python SDK, Docker Compose, Caddy 2, Vite; pytest with existing PostgreSQL testcontainers fixtures.

**Spec:** `docs/superpowers/specs/2026-09-29-lean-production-monitoring-design.md` (approved).

## Global Constraints

- The parent MVP explicitly excludes a full metrics platform.
- Monitoring errors are isolated from publication and review processing.
- Production schema changes run through `python -m dojo.schema`, not application startup DDL.
- Preserve `/health` as a cheap backend liveness endpoint. Add `/ready` for a bounded database connectivity check.
- Proposed defaults: 120 seconds idle maximum age and 3,600 seconds busy maximum age, both configurable and validated.
- Bound production container log retention to three 10 MiB files per service.
- Every 60 seconds, sample available bytes and total capacity on configured paths.
- Open a low-space incident below 15% free. Recover at or above 20% free.
- Retry transient failures with exponential backoff starting at 60 seconds and capped at 3,600 seconds.
- Delivery is at least once. An FCM acceptance response means provider acceptance, not proof of display.
- Use Turkish titles and concise bodies; never raw exception messages.
- Operational alerts do not inherit review reminder cadence or quiet hours.
- Provision two hosted checks, each at a five-minute interval or faster.
- Keep issue #22 open until actual Android delivery and hosted monitoring are demonstrated.

## Review Focus

1. A render still making legitimate progress must not become unhealthy after the idle limit; a stuck render must eventually fail its busy deadline. Task 1.
2. A failed execution is retried before a periodic scan, or the process crashes after committing failure: the original failure alert must survive. Task 3.
3. A notification succeeds externally but acknowledgement is lost, a lease expires, or a device is revoked/token rotates: bounded at-least-once behavior and no stale-token leaks. Task 4.
4. The API is down while the SPA still returns HTTP 200, or dedicated-domain Caddy redirects loopback HTTP: readiness must fail while web health remains independent. Tasks 1 and 6.
5. A low-disk incident survives restart, samples arrive out of order, or a mount cannot be sampled: no duplicate incident or false recovery. Tasks 3 and 5.

## Repository Findings and Delivery Gates

- Production Compose already checks backend `/health` and gateway `/health`; the latter currently checks the API, not the web build. Worker has no health probe.
- `process_job` handles expected media/render failures without raising. `PostgresStore._update_job` is the durable failure transition; monitor that state, not only worker exceptions.
- `FcmNotifier` exists, but currently passes the domain `Notification` to the SDK, lacks app initialization, and treats missing SDK methods/unknown response shape as success. Task 4 makes real delivery trustworthy.
- `worker/pyproject.toml` does not install Firebase Admin. Production Compose does not yet expose FCM credentials.
- Android contains only `MainActivity.kt` displaying a label. #32 (pairing/shell) and #36 (FCM receiver) are open. Do not assume an existing Android message handler. Tasks 1–6 can proceed; Task 7's real-device acceptance depends on that client work. This plan does not silently absorb those full issues.
- No hosted-monitor account/provider or production access has been supplied. Task 7 explicitly provisions and verifies it when access is available; a runbook is not proof of provisioning.

## File Map and Sequence

1. Health: new `worker/health.py`, backend readiness adapter, health asset and gateway routing; probe tests.
2. Logging: new shared `dojo/observability.py`, backend logging entry point; secret-safe formatter tests.
3. Durable state: new monitoring models/ports, migrations `0015_operational_monitoring.py` and `0016_monitoring_checks.py`, matching PostgreSQL/in-memory methods; migration/concurrency tests.
4. Delivery: real FCM adapter and new `dojo/monitoring.py` delivery service; per-recipient retries/tests.
5. Collection/integration: disk sampling/config and worker monitoring invocation; end-to-end failure/incident tests.
6. Deployment: Compose health/logging/secrets wiring, runtime gateway verification, operator runbook.
7. Live acceptance: hosted checks and Android delivery, recording actual evidence and unresolved dependencies.

Execute in order. Keep monitoring code separate from the already large `publishing.py`; existing adapters retain their common persistence boundary. Within each task, implement only after its regression tests fail for the expected missing behavior. Commit only that task's files.

### Task 1: Truthful backend, worker, and web health

**Files:** Create `backend/src/backend/readiness.py`, `backend/tests/test_health.py`, `worker/src/worker/health.py`, `worker/tests/test_health.py`, `web/public/web-health.txt`. Modify `backend/src/backend/routes/health.py`, `backend/src/backend/main.py`, `worker/src/worker/main.py`, `ops/gateway/Caddyfile`.

**Interfaces:**
- `DatabaseReadiness(url: str)` exposes `check() -> bool` and `close() -> None`; owns a dedicated small engine with a 0.5-second pool timeout, 2-second connect timeout and 1-second statement timeout, no schema writes. Keep the combined timeout budget below the 5-second container probe timeout.
- Extend `create_app` with optional `readiness: Callable[[], bool] | None = None`. Production lifespan installs/disposes the real probe; tests inject one.
- `/ready`: 200 `{"status":"ok"}` or 503 `{"status":"unavailable"}`; dependency exceptions map to 503. `/health` retains its existing response.
- `WorkerHealth(path: Path, *, idle_seconds: float = 120, busy_seconds: float = 3600)` exposes `idle() -> None`, `busy() -> None`, `stopped() -> None`. `check_health(path: Path) -> bool`; `python -m worker.health` exits 0/1.
- Worker health JSON contains version, phase, boot identifier, monotonic write time and fixed deadline. Use Linux boot ID plus monotonic time so reboot/stale files cannot pass. CLI and worker use the same container-local file, default `/tmp/dojo-worker-health.json`.
- `/web-health.txt` returns exactly `dojo-web-ok\n`, served only from the built asset; missing asset must return 404, never SPA fallback.

- [ ] **Step 1: Add failing health tests.** Cover injected readiness false/exception/recovery, response redaction, and unchanged liveness. With an injected/monkeypatched monotonic clock, assert idle at age 119 is healthy and age 120 is not; busy at 121 is healthy and 3,600 is not. Reject missing/corrupt/wrong-boot/stopped records and nonfinite/negative timeout values. Assert a tick blocked before returning cannot keep renewing its deadline.

  Core HTTP assertion (no lifespan context is needed for this injected probe):
  ```python
  def test_unready_backend_keeps_liveness():
      client = TestClient(create_app(readiness=lambda: False))
      assert client.get("/ready").status_code == 503
      assert client.get("/ready").json() == {"status": "unavailable"}
      assert client.get("/health").json() == {"status": "ok"}
  ```
- [ ] **Step 2: Run tests red.** `uv run --project backend pytest backend/tests/test_health.py -q` and `uv run --project worker pytest worker/tests/test_health.py -q`; expect missing interfaces or failing assertions.
- [ ] **Step 3: Implement probes.** Create readiness only in lifespan, not at import. Write worker state via same-directory temporary file and atomic replacement. Mark busy immediately before a tick, idle after it, stopped in final cleanup. Do not use a heartbeat thread. Validate the configured idle deadline exceeds `WORKER_INTERVAL_SECONDS`. Do not reset a busy deadline until the tick returns.
- [ ] **Step 4: Route web/API checks separately.** Add `/ready` to the backend matcher. Add an exact static-asset handler before SPA fallback. Add a loopback-only gateway listener on `127.0.0.1:8081` serving the same asset without domain redirects; do not publish that port.
- [ ] **Step 5: Run tests green.** Repeat Step 2 and existing worker tests. Gateway runtime coverage is completed in Task 6, rather than a test that merely greps the Caddyfile.
- [ ] **Step 6: Commit.** `feat(health): add production readiness probes`

### Task 2: Structured, secret-safe process logs

**Files:** Create `dojo-core/src/dojo/observability.py`, `dojo-core/tests/test_observability.py`, `backend/src/backend/serve.py`. Modify `backend/Dockerfile`, `worker/src/worker/main.py`; gateway access-log changes belong to Task 6.

**Interfaces:** `configure_logging(service: str) -> None` configures root and Uvicorn loggers idempotently; `JsonFormatter(service: str)` produces one JSON object per physical line. `python -m backend.serve` starts the existing app on port 8000 using that configuration without Uvicorn replacing it.

Fields: `timestamp` (UTC ISO 8601), `level`, `service`, `event`; optional allowlisted `job_id`, `alert_id`, `status`, `error_type`, `duration_ms`, HTTP method/status. Explicit `event` is a stable literal; legacy records use logger name as fallback. Never serialize arbitrary `extra`, request headers/bodies, raw SQL parameters, or exception text. For unexpected exceptions preserve exception class and stack frame file/function/line, without local variables or source lines. Access logs omit query strings; signed artifact paths are replaced by a fixed route label. Suppress unsafe legacy message interpolation rather than attempting to recognize every possible credential.

- [ ] **Step 1: Add failing formatter tests.** Parse each output line with `json.loads`; assert stable event/service and safe IDs. Parameterize secrets in message arguments, exception text, URL paths/queries, nested extras and multiline strings; assert none occur in encoded output. Repeat configuration twice and assert one record, not duplicated handlers.
- [ ] **Step 2: Run red.** `uv run --project dojo-core pytest dojo-core/tests/test_observability.py -q`.
- [ ] **Step 3: Implement logging and startup wiring.** Initialize logging before backend/worker dependency construction. Add explicit events for startup, shutdown, tick failures and job outcomes; retain useful safe categories and identifiers. Test log formatting with actual Uvicorn-shaped access records.
- [ ] **Step 4: Run green.** Repeat Step 2; run `uv run --project backend pytest backend/tests -q` and `uv run --project worker pytest worker/tests -q`.
- [ ] **Step 5: Commit.** `feat(logging): add safe JSON process logs`

### Task 3: Durable failure events, disk incidents, and delivery claims

**Files:** Create `dojo-core/src/dojo/monitoring_models.py`, `dojo-core/src/dojo/monitoring_ports.py`, `dojo-core/migrations/versions/0015_operational_monitoring.py`, `dojo-core/migrations/versions/0016_monitoring_checks.py` (CHECK constraints on alert kind, delivery status and attempts), `dojo-core/tests/test_monitoring_store.py`. Modify `dojo-core/src/dojo/adapters/db.py`, `dojo-core/src/dojo/adapters/memory.py`, `dojo-core/src/dojo/schema_checks.py`, `dojo-core/tests/conftest.py`, `dojo-core/tests/test_schema_init.py`.

**Data contract:**
- `DiskSample(target: str, free_bytes: int, total_bytes: int, sampled_at: datetime)`.
- `OperationalAlert(alert_id: str, event_key: str, kind: str, title: str, body: str, data: dict[str, str], created_at: datetime)`.
- `DeliveryLease(delivery_id: int, claim_id: str, alert: OperationalAlert, client_id: int, token: str, attempt: int)`; token stays inside transport/persistence, never logs or notification data.
- Tables: `monitoring_incidents` (target primary key, active incident ID, last sample timestamp), `operational_alerts` (unique event key, recipient-snapshot timestamp), `operational_deliveries` (unique alert/client, token fingerprint, status, attempts, due time, claim ID and lease deadline). Reference existing client identities; fetch current tokens from registrations, not duplicated plaintext token columns.
- Add `jobs.failure_generation` integer, default 0. Under a job-row lock, each nonfailed → failed transition increments it and inserts `job:{job_id}:failure:{generation}` in the same transaction. Repeated updates of an already failed row do not emit again. Memory adapter follows the same semantics.
- Migration backfills each existing failed job once with generation 1 and a safe failure alert; timestamp falls back from `finished_at` to `created_at`. Fresh `create_all` and versioned migration must agree. Extend test-fixture cleanup for all new tables.

**MonitoringStore methods (PostgresStore and InMemoryStore):**
- `record_disk_sample(sample: DiskSample, *, low_percent: float, recovery_percent: float) -> None`: lock target state, ignore older/equal samples, atomically emit incident opening/recovery. Opening/recovery event keys contain target plus incident UUID and transition type.
- `prepare_alert_deliveries(now: datetime, *, limit: int = 100) -> int`: snapshot active paired Android clients once when at least one exists. No clients leaves the alert pending. Snapshot completion and delivery-row inserts are atomic. New devices after snapshot are not historical recipients.
- `claim_alert_delivery(now: datetime, *, lease_seconds: int = 60) -> DeliveryLease | None`: row locking with skip-locked, due-time ordering; increment attempt and issue a new fenced claim. Recheck active registration/revocation, use latest token, skip completed recipients. One recipient per claim keeps FCM calls bounded.
- `finish_alert_delivery(lease: DeliveryLease, *, outcome: Literal["accepted", "invalid", "retry"], now: datetime) -> bool`: only current unexpired claim may acknowledge; schedule retry after `min(60 * 2**(attempt-1), 3600)` seconds with overflow-safe capped calculation. Successful recipients remain complete. Invalid registration deletion must compare the exact token used, never remove a newer rotated token; rotation leaves this delivery retryable. Expired/stale acknowledgement returns false.

- [ ] **Step 1: Add memory/PostgreSQL contract tests.** Assert first/repeated failure yields 1 alert; failed → queued → processing → failed yields 2, even before any collector runs. Simulate failure transaction rollback and assert neither job transition nor alert persists. Use real concurrent database connections to assert one incident per transition and one active lease per delivery.
- [ ] **Step 2: Pin restart and timing behavior.** Reopen the store after failure, recreate service objects, and claim the retained alert. Assert no recipients leaves it pending; partial successes are not reclaimed; stale claim completion returns false. Disk samples at 14/15/19/20 percent produce opening/no opening/no recovery/recovery as appropriate; old low samples after recovery do nothing.

  Pin the boundary sequence in a fresh-store test: 15% → 14% → 19% → 20%.
  Query persisted alerts in creation order through the test's database fixture;
  for memory-store contract tests inspect its recorded alert collection:
  ```python
  assert [alert.kind for alert in recorded_alerts] == ["disk.low", "disk.recovered"]
  assert len({alert.event_key for alert in recorded_alerts}) == 2
  assert store.finish_alert_delivery(stale_lease, outcome="accepted", now=now) is False
  ```
- [ ] **Step 3: Run red.** `uv run --project dojo-core pytest dojo-core/tests/test_monitoring_store.py dojo-core/tests/test_schema_init.py -q`; PostgreSQL tests require Docker.
- [ ] **Step 4: Implement model, migration, adapters and ports.** Keep send operations outside transactions. Declare safe fixed notification text centrally in `monitoring_models.py`: `Disk alanı azalıyor`, `Disk alanı normale döndü`, `İş başarısız oldu`; bodies contain configured target labels or job kind/ID, never paths or stored error text. Include data `type=operational_alert`, `alert_id`, `kind`; optional safe `job_id`.
- [ ] **Step 5: Verify migrations green.** Test fresh initialization, upgrade from 0014 with existing failed jobs, repeated initialization, legacy adoption regression, and downgrade removing only new objects. Run Step 3 plus `test_store_jobs.py` and `test_emission_idempotency.py`.
- [ ] **Step 6: Commit.** `feat(monitoring): persist operational alert state`

### Task 4: Reliable real FCM delivery and retry service

**Files:** Create `dojo-core/src/dojo/monitoring.py`, `dojo-core/tests/test_monitoring_delivery.py`, `dojo-core/tests/test_fcm.py`. Modify `dojo-core/src/dojo/adapters/fcm.py`, `dojo-core/src/dojo/__init__.py`, `dojo-core/pyproject.toml`, `worker/pyproject.toml`, `worker/src/worker/main.py`, `uv.lock`.

**Interfaces:**
- Keep `Notifier.send(Notification, list[str]) -> NotificationResult`. Convert the domain notification to `firebase_admin.messaging.Notification`; initialize/reuse an SDK app using Application Default Credentials with a 10-second HTTP timeout. Configure project identity and resolve credentials at startup when FCM is enabled; errors fail startup clearly. SDK injection remains available to unit tests.
- Add Firebase Admin to worker runtime dependencies and dojo-core's development dependencies (resolve the same compatible release and lock it). Production image must import it; dojo-core production users without FCM need not install it. Core CI can test real SDK message construction without relying on incidental workspace installs.
- `DojoMonitoring(store: MonitoringStore, notifier: Notifier, clock: Clock)` exposes `deliver_pending(*, limit: int = 100) -> int`, returning provider-accepted recipient count. Prepare snapshots then claim/send/finish one recipient at a time; cap each invocation to 20 seconds of monotonic elapsed time between calls. A single request can add up to its configured timeout.
- Missing methods, malformed/truncated responses or unmapped recipients never count as accepted. Every input token belongs to exactly one result category. Treat only proven invalid/unregistered token errors as invalid; generic invalid-argument errors may be bad payload and must not delete registrations. Chunk other existing batch callers at the SDK's documented limit.
- Operational notifications include Android tag `alert_id` for duplicate replacement in background. Foreground display uses the same stable ID in the Android integration contract.

- [ ] **Step 1: Add failing transport tests.** Use the actual SDK message types with a fake network sender; assert SDK `Notification` conversion, stable tag, string-only data, bounded batch sizes and initialization reuse. Missing/short responses must retry, not silently succeed. Assert configuration failure does not fall back to StubNotifier.
- [ ] **Step 2: Add failing delivery tests.** Use deterministic clocks and Task 3 stores: success, partial success across recipients, transport exception, no devices, revoked device, rotated token, and expired claim. Assert retry due at 60, 120, 240 seconds and cap at 3,600. Simulate send success followed by DB acknowledgement failure; re-delivery retains identical `alert_id` and tag.

  For a first failed attempt at `now`, these public-store assertions pin the
  retry boundary (fixture has exactly one recipient and one pending alert):
  ```python
  assert store.claim_alert_delivery(now + timedelta(seconds=59)) is None
  retry = store.claim_alert_delivery(now + timedelta(seconds=60))
  assert retry is not None
  assert retry.attempt == 2
  assert retry.alert.alert_id == original_lease.alert.alert_id
  ```
- [ ] **Step 3: Run red.** `uv run --project worker pytest dojo-core/tests/test_fcm.py dojo-core/tests/test_monitoring_delivery.py -q` (worker environment includes the SDK).
- [ ] **Step 4: Implement adapter and delivery loop.** Default-disabled development monitoring must not mark real pending alerts delivered through a stub. Tests inject a stub explicitly. Export `DojoMonitoring` through `dojo.__init__`; keep provider code in the FCM adapter.
- [ ] **Step 5: Run green.** Repeat Step 3 plus existing notification/review/publication tests; verify production worker image imports Firebase Admin in Task 6.
- [ ] **Step 6: Commit.** `feat(monitoring): deliver durable FCM alerts`

### Task 5: Collect disk state and wire worker monitoring

**Files:** Create `worker/src/worker/monitoring.py`, `worker/tests/test_monitoring.py`, `dojo-core/tests/test_monitoring_failures.py`. Modify `worker/src/worker/main.py`, `dojo-core/src/dojo/monitoring.py`, `worker/tests/test_worker.py`.

**Interfaces:**
- `MonitoringConfig.from_env(env: Mapping[str, str], *, media_root: Path) -> MonitoringConfig` validates finite interval/percent values and named absolute disk paths. Environment: `MONITORING_ENABLED` default false locally, `MONITORING_INTERVAL_SECONDS=60`, `MONITORING_DISK_LOW_PERCENT=15`, `MONITORING_DISK_RECOVERY_PERCENT=20`, `MONITORING_DISK_PATHS` JSON object default `{"media":"<MEDIA_ROOT>","root":"/"}`. Require `0 < low < recovery <= 100`, interval > 0, nonempty target names/paths.
- `DiskSampler.sample(target: str, path: Path, at: datetime) -> DiskSample` uses `shutil.disk_usage`; reject zero/invalid totals, exceptions leave incident state unchanged.
- `MonitoringRunner.tick() -> None` samples each target independently, records transitions then calls `DojoMonitoring.deliver_pending`. `MonitoringRunner.run(stop: threading.Event) -> None` invokes it immediately and schedules subsequent turns every 60 seconds using monotonic deadlines and interruptible waits; after an overrun, skip missed turns instead of spinning. Sampling and sending failures are logged independently and never escape into job processing.
- Run this collector in one lightweight thread per worker, so a long synchronous render cannot suppress disk sampling for an hour. It is not a heartbeat thread and must never renew the main worker's busy deadline. Build monitoring with its own store/session boundary and the real notifier, not publishing's private ports or a session shared across threads. Task 3 coordinates duplicate samples and competing deliveries across workers.
- Do not create schema outside the existing initialization contract. Enabling monitoring requires FCM enabled and valid credentials. Start the collector after startup validation; stop it with the same shutdown event, bounded join, and final resource disposal. Existing 120-second container stop grace remains the outer bound.

- [ ] **Step 1: Add failing config/sampling tests.** Reject NaN/infinity and reversed thresholds; simulate a failed mount sample while another target recovers. Assert failure leaves incident open and retry waits until the next interval. Restart runner at 14% with existing incident and assert no duplicate opening.
- [ ] **Step 2: Add failure-path integration tests.** Use real `DojoPublishing.process_job` with a missing staged upload and a rejected render; each must persist a failed job plus alert despite returning normally. An unexpected exception without a terminal state remains a logged execution error, not a fabricated successful/failed job transition.
- [ ] **Step 3: Add worker integration tests.** Block a render with a synchronization event and verify a separately scheduled disk sample still runs without renewing the worker busy deadline. Monitoring has no emission transaction/session context; errors do not skip the job. Followers may also deliver without duplicate durable claims. Disabled mode neither sends nor acknowledges queued alerts. Verify stop interrupts the collector wait and no catch-up tight loop after an overrun. Preserve all scheduler-leadership tests.
- [ ] **Step 4: Run red.** `uv run --project worker pytest worker/tests/test_monitoring.py worker/tests/test_worker.py dojo-core/tests/test_monitoring_failures.py -q`.
- [ ] **Step 5: Implement runner and integration.** Start/join the monitoring loop in `main`, preserving `run_tick` callers. Log bounded safe events for sampling failures, incident changes and delivery results. Worker health busy phase covers the main tick; collector activity cannot conceal a stuck job.
- [ ] **Step 6: Run green.** Repeat Step 4 and Task 3/4 tests.
- [ ] **Step 7: Commit.** `feat(worker): run production monitoring checks`

### Task 6: Production wiring and executable deployment verification

**Files:** Modify `ops/docker-compose.prod.yml`, `ops/.env.example`, `ops/gateway/Caddyfile`, `ops/verify-prod.sh`, `.github/workflows/ci.yml`, `README.md`. Create `ops/docker-compose.monitoring.yml`, `ops/verify-monitoring.sh`, `docs/rehberler/production-monitoring.md`, `docs/contracts/operational-alerts.md`.

**Deployment contract:**
- Base production file gets backend readiness, worker health CLI and loopback web health checks plus bounded logging. Keep both existing proxy modes and named volume identities intact.
- New monitoring override enables `MONITORING_ENABLED=true`, `FCM_ENABLED=true`, mounts `${FCM_CREDENTIALS_FILE}` as a read-only Compose secret at `/run/secrets/firebase-credentials.json`, and sets `GOOGLE_APPLICATION_CREDENTIALS` to that path. Require the host path when using this override; CI base config needs no private credentials.
- Health env: `WORKER_HEALTH_PATH=/tmp/dojo-worker-health.json`, `WORKER_HEALTH_IDLE_SECONDS=120`, `WORKER_HEALTH_BUSY_SECONDS=3600`. Worker/gateway probes run every 15 seconds, timeout 5 seconds, retries 3, start period 30 seconds. Backend readiness is bounded within its probe timeout.
- Use Docker's `json-file` driver with `max-size: 10m`, `max-file: "3"` for every production service. For gateway JSON access logs, remove request headers and the full URI and retain safe method/status/timing fields; do not rely on masking only known query parameter names.
- Runbook maps PostgreSQL, media and Docker log host filesystems. Where not covered by default disk targets, show an extra read-only directory bind and named `MONITORING_DISK_PATHS` target. Never mount the Docker socket. Include exact Compose commands using base + chosen proxy mode + monitoring override.

- [ ] **Step 1: Add failing runtime verification.** `ops/verify-monitoring.sh` uses a uniquely named disposable project, synthetic env and isolated images/volumes. Build/start gateway in both modes (local TLS test configuration for dedicated mode), request actual public/probe routes, remove health asset in the disposable container and assert 404, stop disposable backend and assert `/ready` fails while web health still succeeds. Assert logs contain valid JSON and no synthetic URL/header secrets. Cleanup must target only its own project.
- [ ] **Step 2: Run red.** `bash ops/verify-monitoring.sh`; expect failed health/logging assertions before wiring. Extend existing verification with rendered-config assertions for all health checks and log bounds, rather than string-matching YAML only.
- [ ] **Step 3: Implement Compose/gateway wiring.** Verify Caddy configuration with `caddy validate` inside its image. Check Firebase import in the built worker image and startup rejection with an invalid synthetic credential file. CI renders the monitoring override with a temporary dummy file; it must never send real notifications.
- [ ] **Step 4: Write operational instructions and client contract.** Include settings/defaults, log commands, health diagnosis, the fact that unhealthy containers are not automatically restarted, FCM credential setup, disk coverage mapping, first-enable failed-job backfill, retry semantics and secret-safe troubleshooting. Contract specifies `type=operational_alert`, `alert_id`, `kind` (`disk.low`, `disk.recovered`, `job.failed`), optional `job_id`, Turkish title/body and stable notification ID/tag. No review ID is required; tapping opens the app dashboard. Link #32/#36 prerequisites and foreground/background acceptance steps.
- [ ] **Step 5: Run green.** `bash ops/verify-prod.sh`, `bash ops/verify-monitoring.sh`; run each package's Ruff, mypy and pytest commands from `.github/workflows/ci.yml`, then `npm run build` in `web`. Do not use real `ops/.env` or print rendered secret values. If Docker/Linux tooling is unavailable, report that blocker rather than mark runtime verification complete.
- [ ] **Step 6: Commit.** `feat(ops): wire production monitoring`

### Task 7: Hosted checks and Android acceptance evidence

**Files:** Create `docs/verification/issue-22-production-monitoring.md`; update `docs/rehberler/production-monitoring.md` with actual provider-specific setup once selected. Android code is owned by #32/#36; this task verifies their receiver implements Task 6's contract and requests targeted corrections there if needed.

**Consumes:** Public HTTPS origin, deployed stack access, configured Firebase project, a paired Android build with FCM receiver/notification permission, and an operator-owned hosted-monitor account. Missing inputs are explicit pending acceptance items, not an invitation to create a paid account or fabricate monitor IDs.

- [ ] **Step 1: Record prerequisites and verification identity.** Deployed commit, image tags, date, sanitized origin, device/build, provider/account owner. Use named evidence fields for health, logs, disk alert/recovery, failed-job alert, retry recovery, web/API monitors, outage/recovery receipt. Never record secrets or device tokens.
- [ ] **Step 2: Provision hosted checks.** In the operator's selected hosted service, configure HTTPS GET for `/web-health.txt` expecting `dojo-web-ok` and `/ready` expecting the ready JSON response, with certificate validation, interval at most 5 minutes and an independent outage/recovery notification contact. Confirm provider supports body checking so SPA fallback cannot pass. Fetch current provider docs before setup. Record monitor IDs and observed status.
- [ ] **Step 3: Verify Android delivery.** On a disposable deployment configured with the same FCM project/device registration flow, trigger a synthetic failed job and simulate low/recovered disk samples without filling a production disk. Observe Turkish notifications foreground and background, no review ID dependency, repeated stable ID replacement, and recovery after a temporary transport failure. No receiver/build means this step remains blocked by #32/#36.
- [ ] **Step 4: Verify deployment health and outage detection.** Capture all three health statuses and sample sanitized JSON log lines. Arrange a controlled test window for the real hosted check, interrupt the monitored service, receive its independent alert, restore it and receive recovery. Avoid unannounced production disruption; a disposable public deployment can exercise the drill first.
- [ ] **Step 5: Record actual results.** Pass/fail/pending per acceptance criterion with evidence references. Keep #22 open while any required live criterion remains pending. Commit evidence without secrets: `docs: record monitoring acceptance evidence`.

## Self-Review

- Health, long-job deadlines, static web independence and bounded readiness: Tasks 1/6.
- Structured logs, redaction and retention: Tasks 2/6.
- Crash-safe failure capture, existing failure backfill and per-recipient delivery: Tasks 3/4.
- Disk hysteresis, bad samples, configuration, worker integration: Tasks 3/5.
- FCM runtime installation/initialization and safe production credentials: Tasks 4/6.
- Android message contract and honest live-delivery gate: Tasks 6/7; #32/#36 explicitly identified.
- Hosted monitor presence and independent outage/recovery evidence: Task 7.
- All five Review Focus cases have targeted tests or executable drills above.

## Execution Choice

Recommended: native execution in this session, followed by independent whole-branch review. The six code/documentation tasks share persistence and notification interfaces closely; keeping that context together reduces handoff overhead. Task 7 has external prerequisites regardless of execution method. Alternative: fresh implementer/reviewer subagents per task for stronger incremental review at higher context cost.
