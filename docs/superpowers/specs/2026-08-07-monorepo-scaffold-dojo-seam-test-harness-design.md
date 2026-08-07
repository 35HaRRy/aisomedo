# Monorepo Scaffold, Deep Dojo Publishing Seam, and Test Harness

## Parent

Issue #2 — foundation for #1 (Dojo Reel Publishing MVP). Blocked by nothing; blocks #3 and #21.

## Goal

A working monorepo skeleton: FastAPI backend, dedicated worker process, PostgreSQL, and
placeholder modules for the web and Android clients. The deep `Dojo Publishing` module
interface is the single behavioral seam consumed by FastAPI routes and scheduler triggers.
A test harness runs against real PostgreSQL and deterministic FFmpeg fixtures, replacing
only Meta publishing, notification delivery, wall clock, and signed-URL delivery with
adapters. CI builds everything and keeps it green.

## Acceptance criteria

- Monorepo with backend/worker/web/android/ops modules present and building.
- `Dojo Publishing` interface exposed and consumed by both routes and worker triggers.
- Test harness brings up real PostgreSQL + FFmpeg fixtures; a smoke test drives one
  command through the seam and asserts an observable outcome.
- CI pipeline runs and passes.

## Decisions (brainstorming)

- uv workspace, three Python packages: `dojo-core` (the seam + adapters), `backend`
  (FastAPI), `worker` (scheduler). Single lockfile; each process installs only its own deps.
- Seam shape: facade class (Approach A). One `DojoPublishing` facade; adapter ports are
  injected Protocols. Rejected function-based and event-driven seams as over-abstracted.
- Full future interface declared as typed signatures; one command live end-to-end:
  `ensure_active_package`. The rest raise `NotImplementedError`.
- Backend exposes a real route (`GET /api/packages/active`) that calls the seam; worker runs
  a scheduler loop that calls `evaluate_due_work()` on each tick. Both consume an
  adapter-injected `DojoPublishing` instance.
- Test harness: testcontainers-python for real PostgreSQL and an FFmpeg image. Deterministic
  tiny JPEG/MP4 fixtures generated on the fly inside the ffmpeg container. No machine-level
  Postgres/FFmpeg installs required.
- Placeholders: `web/` = Vite + React + TS stub dashboard that typechecks and builds;
  `android/` = Gradle wrapper + minimal Kotlin project (settings + app module) building an
  empty launcher. Android not built locally (no SDK on dev machine); validated in CI later.
- CI: GitHub Actions — Python job (lint + typecheck + pytest with testcontainers), web job
  (install + build + typecheck), ops compose config validation. Android build deferred.

## Architecture

```
backend/       FastAPI app (uv package) — deps: dojo-core, fastapi, uvicorn
worker/        scheduler process (uv package) — deps: dojo-core
dojo-core/     the seam — deps: sqlalchemy, psycopg, alembic
web/           Vite + React + TS placeholder dashboard
android/       minimal Gradle app (settings + empty launcher)
ops/           docker-compose.yml, .env.example, compose config check
.github/workflows/ci.yml
```

### dojo-core (the seam)

```
dojo-core/src/dojo/
  ports.py        Protocols: Clock, MetaPublisher, Notifier, SignedUrlStore (+ stub impls)
  model.py        Package, Manifest, AuditEvent dataclasses
  publishing.py   DojoPublishing facade
  adapters/
    db.py         SQLAlchemy Postgres store + alembic migrations
    fs.py         filesystem package store (folders + manifest.json)
    clock.py      SystemClock
```

`DojoPublishing` full interface (declared; only `ensure_active_package` live):

- `ensure_active_package() -> Package`
- `get_active_package() -> Package | None`
- `add_media(...)`, `resolve_conflict(...)`, `remove_media(...)`, `restore_media(...)`
- `set_order(...)`, `set_caption(...)`, `set_branding(...)`
- `create_review()`, `approve(...)`, `skip(...)`, `reschedule(...)`
- `render_preview()`, `publish()`
- `evaluate_due_work()`
- `list_audit()`

`ensure_active_package` behavior:

1. Enforce zero-or-one active package invariant.
2. Create folder named `dd-MM-yyyy HH-mm` in `Europe/Istanbul` (SystemClock by default,
   fake clock in tests).
3. Write `manifest.json` (empty media, explicit empty order, no render revision).
4. Insert one active row in Postgres.
5. Append structured audit event.
6. Return `Package`.

### backend

- `create_app(deps)` factory; DI wires `DojoPublishing` with adapters.
- `GET /api/packages/active` -> `get_active_package()`; 404 mapping when absent.
- Health route. DB session management.

### worker

- `main.py`: loop; each tick calls `seam.evaluate_due_work()` (no-op for now).
- SIGTERM graceful shutdown.

### web

- Vite + React + TS; stub dashboard page; `tsc --noEmit` and `vite build` pass.

### android

- Gradle wrapper + `settings.gradle.kts` + `app` module with empty Compose-free launcher
  activity placeholder. Buildable when SDK present; not built in CI yet.

### ops

- `docker-compose.yml`: postgres, backend, worker, media volume.
- `.env.example`; `docker compose config` validates.

## Data flow

Route/worker -> `DojoPublishing` facade -> adapters (Postgres store, filesystem store,
clock) -> observable domain outcome (folder, manifest, DB row, audit entry).

## Error handling

- Domain exceptions on the seam: `ActivePackageExists`, `NoActivePackage`,
  `NotImplementedError` for declared-but-stubbed commands.
- Routes map domain exceptions to HTTP (409/404/501).
- Infra failures (DB, disk) isolated in adapters, surfaced as generic 500 upstream.

## Testing

- `dojo-core` pytest suite; testcontainers spins real Postgres + FFmpeg image.
- Fixture util generates deterministic tiny JPEG/MP4 via ffmpeg container.
- Smoke test: fake clock + stub MetaPublisher/Notifier/SignedUrlStore -> call
  `ensure_active_package` -> assert observable outcome: folder with correct name,
  manifest present, one active DB row, audit entry.
- Harness check: assert ffmpeg-generated fixture validity via ffprobe metadata.
- Unit tests: port Protocol contract checks, store/fs adapters in isolation.
- Typecheck: `uv run mypy` on all three packages. Lint: ruff.
- Full suite once at the end.

## CI (GitHub Actions)

- Python job: setup uv, install workspace, ruff, mypy, pytest (testcontainers Postgres +
  FFmpeg; GH runner has Docker).
- Web job: npm ci, `tsc --noEmit`, `vite build`.
- Ops job: `docker compose -f ops/docker-compose.yml config`.
- Android build deferred to a later ticket.

## Out of scope

- Any live seam command besides `ensure_active_package`.
- Android build in CI, Android SDK setup.
- Real Meta publishing, real notifications, signed-URL service (stubs only).
- Web UI beyond stub dashboard; Android UI beyond empty launcher.
- Scheduler leadership, recovery, deployment rollout.
