# Dojo Social Publishing

> **Status: WIP / MVP** — this is an early, MVP-scoped implementation. Features listed as *out of scope* in the design spec are not built yet.

A system that helps dojo administrators collect class photos and videos, prepare them, and publish them to Instagram as branded Reels — on a recurring schedule and with a human approval step before anything goes public.

## What it does

- Stores and manages the media files (photos and videos) intended for publication.
- Lets administrators order, trim, and caption a package of media.
- Schedules publication every other Monday on a `Dojo Yayın Planı`.
- Renders an immutable, branded 1080x1920 Reel for review.
- Requires approval (Review / Skip / Reschedule) before any post is published.
- Publishes the exact reviewed artifact through the official Instagram Graph API.
- Keeps an auditable history of every action, and renames a package `-completed` only after Instagram confirms publication.

There are **no user accounts**. Trusted Android devices and browsers are paired once using short-lived, one-time codes; every paired client has equal permissions.

**Stack:** Kotlin (Android), React + TypeScript (web), FastAPI (backend), Python worker (scheduler/render/publisher), PostgreSQL.

## Repository layout

| Path          | Purpose                                                        |
| ------------- | -------------------------------------------------------------- |
| `dojo-core/`  | Shared domain logic, adapters, SQLAlchemy models, Alembic migrations |
| `backend/`    | FastAPI public API and CLI tools                               |
| `worker/`     | Dedicated scheduler / render / publication process             |
| `web/`        | React + Vite web dashboard                                     |
| `android/`    | Kotlin Android app                                             |
| `ops/`        | Docker Compose stack and environment templates                |

## Requirements

- Python 3.12
- Node.js 22 (web)
- Docker (ops stack)
- FFmpeg (media rendering / tests)

## Getting started

### Full stack (Docker Compose)

```bash
cp ops/.env.example ops/.env        # set POSTGRES_PASSWORD
docker compose --env-file ops/.env -f ops/docker-compose.yml up --build
```

The database listens on `5433` and the backend on `8000`.

### Python workspace

```bash
uv sync --all-packages
```

Admin CLI (after `uv sync`), for example to mint a pairing code:

```bash
uv run --project backend dojo-create-pairing-code create-code
uv run --project backend dojo-consent set-policy --version 1 --text "..."
uv run --project backend dojo-settings set-upload-limits --max-file-bytes 2147483648
```

### Web dashboard

```bash
cd web
npm ci
npm run dev
```

## Usage (simple flow)

1. **Pair** an Android device or browser using a one-time pairing code.
2. **Upload** photos and videos into the active package.
3. **Order and trim** the media into the intended montage.
4. **Preview** the rendered, branded Reel.
5. **Approve** the review when the scheduled `Yayın Zamanı` is due.
6. The package is **published** to Instagram and archived as `-completed`.

## Tests

The Python tests use a real PostgreSQL container (Testcontainers) and small FFmpeg media fixtures, so Docker and FFmpeg must be available.

```bash
# Run each package's test suite
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
uv run --project worker pytest worker/tests -v
```

Lint and typecheck:

```bash
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project backend ruff check backend/src backend/tests
uv run --project worker ruff check worker/src worker/tests

uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend mypy backend/src/backend
uv run --project worker mypy worker/src/worker
```

Web build and typecheck:

```bash
cd web
npm run typecheck
npm run build
```

## Domain language

Canonical terminology (`Dojo Paylaşım Paketi`, `Dojo Yayın Planı`, `Yayın Zamanı`, `Yayın İncelemesi`, `Tamamlanmış Paket`) is defined in [`CONTEXT.md`](CONTEXT.md). The full product spec lives in [`docs/specs/dojo-reel-publishing-mvp.md`](docs/specs/dojo-reel-publishing-mvp.md).