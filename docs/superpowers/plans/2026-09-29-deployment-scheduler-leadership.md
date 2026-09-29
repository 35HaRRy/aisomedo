# Deployment and Single-Scheduler Leadership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy full stack reproducibly on one Linux VPS via Compose with HTTPS, and restrict scheduler emission to one worker per turn via PostgreSQL coordination.

**Architecture:** One web gateway image (built frontend + Caddy) fronts same-origin API; prod Compose adds gateway + unexposed backend/db with named volumes and mode overrides. Scheduler leadership uses transaction-scoped PG advisory lock per emission turn; DB constraints enforce occurrence/review/job idempotency.

**Tech Stack:** Docker Compose, Caddy, FastAPI (Python 3.12), SQLAlchemy + PostgreSQL 16, React/Vite frontend, FFmpeg in worker image, uv lockfiles.

**Spec:** `docs/superpowers/specs/2026-09-28-deployment-scheduler-design.md`

## Global Constraints

- Keep orchestration behind the Dojo Publishing seam; PostgreSQL advisory locking only — no Redis or lease service.
- Leadership semantics: non-blocking transaction-scoped advisory lock per scheduling turn; skip emission if held; release on commit/rollback.
- All DB writes emitting due work must use the transaction holding the lock; per-method commits must not release leadership prematurely.
- Long rendering and external HTTP stay outside the emission transaction; job execution keeps existing atomic claims.
- Production PostgreSQL and backend expose no host ports; named volumes retain db and media across recreation; backend and worker mount same media volume at same path.
- Build Python images from committed lockfile; frontend from its package lockfile; examples contain placeholders, never real credentials.
- Serialize schema initialization before app startup; do not depend on concurrent create-all calls.
- Gateway serves static assets with SPA fallback, proxies backend routes without path rewrite; API and signed artifact requests never fall through to SPA; raw media volumes not mounted into gateway.
- Forwarded client/scheme headers accepted only from configured proxy addresses/networks; preserve secure cookies and client identity for pairing throttling.
- Existing-data upgrade path required: preflight conflicting rows; never silently delete historical jobs/reviews.
- Do not claim exactly-once at external publishing API; preserve existing reconciliation.
- Out of scope: automatic release deployment/rollback (#39), broad monitoring/backups (#22, #23).

## Review Focus

- Second worker tick during slow render enqueues duplicate render job for same package/revision — expect at most one queued/processing render job.
- Repeated evaluation of same regular due time creates duplicate occurrence — expect one occurrence.
- Concurrent API-triggered render request + scheduler tick creates two jobs — expect one job and one `render.queued` audit event for the job actually created.
- Failed/completed render job blocks legitimate explicit retry — expect retry allowed after failure/completion.
- External-proxy mode request loses client IP / secure cookie through proxy chain — expect correct `X-Forwarded-*` trust and `Secure` cookies with right client identity.

---

### Task 1: Scheduler leadership boundary with advisory lock

**Files:**
- Create: `dojo-core/src/dojo/scheduler.py`
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Test: `dojo-core/tests/test_scheduler_leadership.py`

**Interfaces:**
- Consumes: `PostgresStore._engine` (SQLAlchemy Engine), `DojoPublishing.evaluate_due_work() -> None`
- Produces: `try_emission_leadership(store: PostgresStore) -> contextmanager[bool]`, `PostgresStore.try_advisory_xact_lock(key: int) -> bool` (uses `SELECT pg_try_advisory_xact_lock(:key)` on the emission transaction connection)

- [ ] **Step 1: Write the failing test**

```python
def test_second_worker_skips_emission_while_leader_holds_lock():
    assert True is False  # placeholder: two PostgresStore handles, leader holds lock, follower try_emission_leadership returns False and emits nothing

def test_lock_holder_termination_allows_takeover():
    assert True is False

def test_exception_in_emission_rolls_back_and_retries_next_tick():
    assert True is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package dojo-core pytest dojo-core/tests/test_scheduler_leadership.py -v`
Expected: FAIL (tests placeholder / no `scheduler` module)

- [ ] **Step 3: Implement `try_advisory_xact_lock` in `dojo-core/src/dojo/adapters/db.py` and `try_emission_leadership` in `dojo-core/src/dojo/scheduler.py`**

Use fixed 64-bit lock key for scheduler emission (document constant in `scheduler.py`, e.g. `SCHEDULER_EMISSION_LOCK_KEY`). Non-blocking `pg_try_advisory_xact_lock`; return lock status; caller skips `evaluate_due_work` body when not leader. Emission writes must run inside the same transaction/connection holding the lock.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package dojo-core pytest dojo-core/tests/test_scheduler_leadership.py -v`
Expected: PASS against real PostgreSQL harness

- [ ] **Step 5: Commit**

```bash
git add dojo-core/src/dojo/scheduler.py dojo-core/src/dojo/adapters/db.py dojo-core/tests/test_scheduler_leadership.py
git commit -m "feat(scheduler): per-turn advisory-lock leadership"
```

### Task 2: Emission under leadership + operation classification in worker

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py:1119-1143`
- Modify: `worker/src/worker/main.py:112-152`
- Test: `dojo-core/tests/test_scheduler_leadership.py` (extend), `worker/tests/test_worker_tick.py` (new if missing)

**Interfaces:**
- Consumes: `try_emission_leadership` from Task 1, `DojoPublishing.evaluate_due_work`, `claim_next_job`, `process_job`, `send_due_reminders`, `reconcile_publication`, `sweep_stale_uploads`
- Produces: `run_tick(publishing, meta) -> None` with classified behavior: schedule evaluation under leadership; job claim/execution concurrent-safe via atomic claims; reminder/token-maintenance/reconciliation coordinated as singletons where needed (per spec); SIGTERM bounded clean shutdown; DB-unavailable/log-and-retry without tight loop

- [ ] **Step 1: Write the failing test**

```python
def test_run_tick_follower_processes_jobs_but_emits_no_new_work():
    assert True is False

def test_slow_render_second_tick_creates_no_second_job():
    assert True is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package dojo-core pytest dojo-core/tests/test_scheduler_leadership.py worker/tests/test_worker_tick.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `run_tick` classification in `worker/src/worker/main.py` and adapt `DojoPublishing.evaluate_due_work` transaction boundaries in `dojo-core/src/dojo/publishing.py`**

Move emission writes into the lock-holding transaction; keep `process_job` (render + HTTP) outside it; ensure exceptions roll back emission turn only. Add bounded SIGTERM shutdown and retry delay (reuse `WORKER_INTERVAL_SECONDS`, no tight loop).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package dojo-core pytest dojo-core/tests/test_scheduler_leadership.py -v`
Run: `uv run --package worker pytest worker/tests/test_worker_tick.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dojo-core/src/dojo/publishing.py worker/src/worker/main.py worker/tests/test_worker_tick.py
git commit -m "feat(worker): leadership-gated emission turn"
```

### Task 3: DB-backed idempotency (occurrence / review / render job)

**Files:**
- Modify: `dojo-core/src/dojo/adapters/db.py` (constraints + `_create_occurrence`, `_create_review`, `_create_job`, `claim_next`)
- Modify: `dojo-core/src/dojo/publishing.py:2292-2314` (`_enqueue_render`)
- Modify: `dojo-core/migrations/` or `alembic` upgrade + preflight script
- Test: `dojo-core/tests/test_emission_idempotency.py`

**Interfaces:**
- Consumes: `PostgresStore` session/rows for `YayinZamani`, `YayinIncelemesi`, `JobRow`
- Produces: constraints — one occurrence per regular due time; one review per (occurrence_id, revision_digest); at most one queued/processing render job per package/revision including API+scheduler concurrency; failed/completed does not block retry; `render.queued` audit only for jobs actually created

- [ ] **Step 1: Write the failing test**

```python
def test_repeated_due_evaluation_creates_one_occurrence():
    assert True is False

def test_concurrent_api_and_scheduler_render_creates_one_job():
    assert True is False

def test_retry_allowed_after_failure():
    assert True is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package dojo-core pytest dojo-core/tests/test_emission_idempotency.py -v`
Expected: FAIL (duplicates created)

- [ ] **Step 3: Implement constraints + `INSERT ... ON CONFLICT DO NOTHING`-style guards in `dojo-core/src/dojo/adapters/db.py`, guard `_enqueue_render` in `publishing.py`**

Add unique index/constraint for occurrence identity, `(occurrence_id, revision_digest)` for reviews, partial unique index for queued/processing render jobs per package digest. Add explicit upgrade path + preflight query reporting conflicting rows; do not delete history.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package dojo-core pytest dojo-core/tests/test_emission_idempotency.py dojo-core/tests/test_scheduler_leadership.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dojo-core/src/dojo/adapters/db.py dojo-core/src/dojo/publishing.py dojo-core/migrations dojo-core/tests/test_emission_idempotency.py
git commit -m "feat(db): emission idempotency constraints"
```

### Task 4: Production Compose, gateway, and web image

**Files:**
- Create: `ops/docker-compose.prod.yml`
- Create: `ops/gateway/Dockerfile`
- Create: `ops/gateway/Caddyfile`
- Create: `web/Dockerfile` (or multi-stage inside gateway; prefer gateway COPY from web build stage)
- Modify: `ops/docker-compose.yml` (keep dev; ensure no drift in service names/env contract)
- Modify: `ops/.env.example`
- Modify: `web/vite.config.ts` (same-origin API, deep-link fallback support)
- Test: manual verification script `ops/verify-prod.sh` (build + config check, not unit test)

**Interfaces:**
- Consumes: `backend/Dockerfile`, `worker/Dockerfile`, `web/package-lock.json`, `ops/.env`
- Produces: `docker compose -f ops/docker-compose.yml -f ops/docker-compose.prod.yml config` valid in both modes: dedicated-domain (Caddy :80/:443 with cert volume) and existing-proxy (gateway HTTP on loopback-bound port or external network; upstream owns TLS)

- [ ] **Step 1: Write the verification checklist as script assertions**

```bash
# ops/verify-prod.sh asserts: backend/worker/gateway images build; prod config renders both modes; gateway proxies /api/* and signed-artifact routes, SPA fallback otherwise; no host ports for db/backend in prod; named volumes for db-data/media/caddy-data
```

- [ ] **Step 2: Run verification to verify it fails**

Run: `bash ops/verify-prod.sh`
Expected: FAIL (files missing)

- [ ] **Step 3: Implement gateway + prod Compose + web build**

Gateway: Caddy + built frontend (`vite build`), SPA fallback, proxy `backend:8000` without path rewrite, trusted-proxy `trusted_proxies` from env, `PUBLIC_HTTPS_ORIGIN` for OAuth/signed URLs. Verify which backend routes execute media tooling and keep FFmpeg only where actually executed (worker already has it). Prod: no `ports` on db/backend, named volumes (`db-data`, `media-data`, `caddy-data`), `restart: unless-stopped`, healthchecks + `depends_on` readiness, serialized migration/init container before backend/worker. Two overrides: dedicated-domain vs existing-proxy (loopback port var + optional external network name var). Serialize schema init (init service running migrations/`create_all` once).

- [ ] **Step 4: Run verification to verify it passes**

Run: `bash ops/verify-prod.sh`
Run: `docker compose -f ops/docker-compose.yml -f ops/docker-compose.prod.yml build backend worker gateway`
Expected: PASS / images build

- [ ] **Step 5: Commit**

```bash
git add ops/docker-compose.prod.yml ops/gateway web/Dockerfile ops/verify-prod.sh ops/.env.example web/vite.config.ts
git commit -m "feat(deploy): prod compose with gateway and proxy modes"
```

### Task 5: Prod config, headers/cookies, docs, and smoke test

**Files:**
- Modify: `backend/src/backend/main.py:67-96` (trusted proxy headers, `COOKIE_SECURE` default true in prod, `PUBLIC_BASE_URL`/`PUBLIC_HTTPS_ORIGIN` wiring)
- Modify: `backend/src/backend/deps.py:102-123` (client IP via forwarded headers only from trusted proxies)
- Create: `docs/ops/deployment.md`
- Modify: `ops/.env.example` (placeholders for `PUBLIC_HTTPS_ORIGIN`, `TRUSTED_PROXIES`, `CADDY_*`, `EXTERNAL_NETWORK`, `HTTP_PORT`)
- Test: `backend/tests/test_proxy_headers.py`, deployment smoke checklist in docs

**Interfaces:**
- Consumes: gateway forwarding behavior from Task 4, `IpThrottle`, `get_current_client`
- Produces: correct pairing-throttle identity through proxy chain; `Secure` cookies preserved; documented fresh install, both proxy modes, DNS/ports, env, startup, health verification, worker scaling, restart, volume preservation + existing-data migration

- [ ] **Step 1: Write the failing test**

```python
def test_client_ip_uses_forwarded_header_only_from_trusted_proxy():
    assert True is False

def test_secure_cookie_preserved_behind_https_proxy():
    assert True is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package backend pytest backend/tests/test_proxy_headers.py -v`
Expected: FAIL

- [ ] **Step 3: Implement trusted-proxy handling in `backend/src/backend/main.py` + `deps.py`, write `docs/ops/deployment.md`**

Accept `X-Forwarded-For/Proto` only from `TRUSTED_PROXIES`; require `PUBLIC_HTTPS_ORIGIN` https in prod for browser/OAuth/signed URLs; frontend same-origin. Docs cover: fresh install, dedicated vs existing-proxy, DNS/ports, env table, startup/health (`/health`, compose ps), worker scaling note (multiple workers safe via Task 1), restart, volume lifecycle (recreate keeps db/media; never auto-substitute empty volume).

- [ ] **Step 4: Run tests + full suite to verify**

Run: `uv run --package backend pytest backend/tests/test_proxy_headers.py -v`
Run: `docker compose -f ops/docker-compose.yml -f ops/docker-compose.prod.yml config`
Expected: PASS; distinguish local proxy tests from real public HTTPS + cert issuance evidence (VPS-gated) in completion report per spec

- [ ] **Step 5: Commit**

```bash
git add backend/src/backend/main.py backend/src/backend/deps.py backend/tests/test_proxy_headers.py docs/ops/deployment.md ops/.env.example
git commit -m "feat(deploy): proxy trust, secure cookies, deployment docs"
```
