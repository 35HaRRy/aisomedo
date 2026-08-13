# Active Dojo Paylaşım Paketi Lifecycle — Design

Date: 2026-08-13
Source: Issue #6 (part of #1, Dojo Reel Publishing MVP), blocked by #3 (done).

## Problem

An installation needs exactly one active `Dojo Paylaşım Paketi` at all times,
represented as a folder plus a manifest, so every new dojo media has one
unambiguous destination. The package must be created automatically on first
use, must never exceed one active instance during normal operation, must
persist the full manifest contract (immutable media identifiers, explicit
order, source metadata, trims, caption, branding, render revision, Meta
identifiers, recovery information), use portable `dd-MM-yyyy HH-mm` timestamps
in `Europe/Istanbul`, and transition to a fresh empty package on completion.

## Decisions

1. **Seam placement**: extend the existing deep `DojoPublishing` facade
   (`dojo/publishing.py`) — the MVP's single primary seam. No new facade.
   Later tickets (#7 media, #11 branding, #15 review, #18 publication) extend
   the same class per the MVP spec.
2. **Completion owned by #6**: `complete_active_package()` renames the folder
   to `-completed`, flips the row to `completed`, and immediately creates the
   next empty active package. #18 calls this seam after Instagram confirms
   publication; the transition itself ships here.
3. **Full manifest schema now**: the manifest file carries all eight contract
   keys from day one, populated with empty defaults. Later tickets fill
   fields without schema drift.
4. **Invariant enforced twice**: facade raises `ActivePackageExists` on a
   second ensure (already done), plus a partial unique index on
   `packages(status) WHERE status='active'` at the DB level to stop two active
   rows under race.
5. **GET auto-creates**: `GET /api/packages/active` returns the existing
   active package or creates one when absent — a read never 404s. `POST
   /api/packages/active` keeps its strict ensure semantics (409 when one
   exists). `POST /api/packages/active/complete` completes and returns the
   next package.
6. **Completion order**: DB row flips to `completed` before the folder rename,
   so a crash between steps leaves a `completed` row rather than a renamed
   folder under an `active` row. The single-active invariant is enforced by
   the partial unique index regardless.
7. **Same-minute collision ignored**: completing and creating the next package
   within the same clock minute would collide on the `dd-MM-yyyy HH-mm` name.
   Deemed unlikely by the operator; no suffix handling in #6. A future ticket
   may add disambiguation if it ever surfaces.
8. **Auth**: package routes sit behind `get_current_client`, same as every
   other `/api` business route. Both paired kinds (device + browser) have
   equal access.

## Domain model

`Manifest` (`dojo/model.py`) grows to the full contract:

- `media: list[dict]` — immutable media identifiers plus source metadata.
  Entry shape: `{"media_id", "filename", "content_type", "size_bytes",
  "uploaded_at", "status"}`.
- `order: list[str]` — explicit media_id ordering.
- `trims: dict` — `{media_id: {"start": s, "end": e}}`.
- `caption: str | None`.
- `branding: dict` — logo, intro/outro choices, per-package overrides.
- `render_revision: str | None` — digest of all render inputs.
- `meta: dict` — Meta identifiers `{container_id, media_id}`.
- `recovery: dict` — `{recovered_from, resolved}`.

`Manifest.to_dict()` emits all eight keys. The initial `manifest.json` written
at creation carries the empty defaults.

`Package` (`dojo/model.py`) unchanged: `id`, `folder_name`, `created_at`,
`status`.

## Storage

Migration `0004_active_package` adds a partial unique index:

```sql
CREATE UNIQUE INDEX ix_packages_status_active
  ON packages (status) WHERE status = 'active';
```

`PackageStore` (`dojo/ports.py`) gains:

- `update(package: Package) -> Package` — replace row by id (folder_name +
  status).

`InMemoryStore` swaps the entry in its list; `PostgresStore` runs
`UPDATE packages SET folder_name=?, status=? WHERE id=?` and returns the
updated row. Reused later by #18's `-publishing` claim.

## Ports

- `PackageStore(Protocol)` gains `update`.
- `Clock`, `AuditStore` unchanged.

## Facade (`dojo/publishing.py`)

- `get_or_create_active_package(*, requester: str | None = None) -> Package` —
  return existing active or create (folder + manifest + row + `package.created`
  audit). Same creation path as `ensure_active_package`.
- `ensure_active_package(*, requester: str | None = None) -> Package` —
  unchanged strict contract; raises `ActivePackageExists` when one exists.
- `complete_active_package(*, requester: str | None = None) -> Package`:
  1. `get_active()` → raise `NoActivePackage` if none.
  2. `update()` row: `status="completed"`.
  3. Rename folder `"<base>"` → `"<base>-completed"` (`Path.rename`).
  4. Update row `folder_name` to the renamed value.
  5. Create the next empty active package (new `dd-MM-yyyy HH-mm` timestamp,
     fresh manifest, new row).
  6. Audit `package.completed` then `package.created`.

### Rules

- Zero-or-one active enforced by facade (`ActivePackageExists`) and the partial
  unique index.
- `get_or_create_active_package` never raises when a package exists; it returns
  it.
- `complete_active_package` with no active package raises `NoActivePackage`.
- After completion, `get_active()` returns the new package, never the completed
  one.

## Exceptions

- `NoActivePackage(DojoError)`.

## FastAPI integration

`backend/routes/packages.py`:

- `GET /api/packages/active` — auth required. Calls
  `get_or_create_active_package(requester=str(client.id))`; returns 200. Never
  404s.
- `POST /api/packages/active` — unchanged strict ensure; `ActivePackageExists`
  → 409.
- `POST /api/packages/active/complete` — auth required. Calls
  `complete_active_package(requester=str(client.id))`; returns the new active
  package. `NoActivePackage` → 404.

No CLI change in #6; completion is route-triggered now, worker wiring in #18.

## Testing

### Domain (`dojo-core/tests/test_publishing.py`, in-memory + real Postgres)

1. `get_or_create_active_package` returns existing when present; creates +
   audits `package.created` when absent.
2. `complete_active_package` renames folder to `-completed`, row status →
   `completed`, creates next active with fresh timestamp folder + empty
   manifest, audits `package.completed` + `package.created`.
3. `complete_active_package` with no active raises `NoActivePackage`; no folder
   created.
4. Zero-or-one invariant: second `ensure_active_package` raises
   `ActivePackageExists`; after completion `get_active()` returns the new
   package, not the completed one.
5. Initial manifest contains all eight keys with empty defaults.
6. Postgres: partial unique index blocks a second `active` row; `pg_store`
   roundtrip of `complete_active_package`.

### Store (`dojo-core/tests/test_store_package.py`, `test_db_adapter.py`)

- `update()` roundtrip on both adapters.
- Migration creates the partial unique index (alembic schema assertion).

### Contract (`backend/tests/test_api.py`)

- GET auto-creates when absent (200, `package.created` audited).
- POST still 409 on second ensure.
- POST `/api/packages/active/complete` completes and returns next package;
  no-active → 404; unauth → 401.

## Out of scope

- Media upload/finalization (#7), branding (#11), review (#15), publication
  (#18), failure recovery (#19), multi-open-folder recovery (#20).
- Same-minute folder-name disambiguation.
- Worker scheduler triggering completion (#18).
- CLI completion entry point.
