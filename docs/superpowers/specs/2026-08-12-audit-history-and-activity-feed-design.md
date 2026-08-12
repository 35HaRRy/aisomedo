# Audit History and Activity Feed — Design

Date: 2026-08-12
Source: Issue #4 (part of #1, Dojo Reel Publishing MVP), blocked by #3 (done).

## Problem

Every meaningful domain action — pairing, uploads, conflicts, edits, reviews,
device actions, state transitions, Meta identifiers, failures, recovery, and
consent — must leave an immutable, append-only audit entry with a timestamp and
the acting paired client. Both clients need recent activity through an Activity
API without VPS access.

## Decisions

1. **Seam placement**: new deep `DojoActivity` facade in `dojo-core`
   (`dojo/activity.py`), alongside `DojoPairing` and `DojoPublishing`. It owns
   the activity read path — newest-first ordering, cursor paging, and
   server-side actor resolution. Scheduler triggers and HTTP routes share it.
2. **Scope now**: deliver the audit/activity substructure, the Activity API, and
   wire the domain actions that exist today (pairing events already emitted;
   `package.created` gets a real actor). The remaining audit facts (destructive
   overwrite, review resolution, state transitions, Meta identifiers, recovery,
   consent) emit through this same immutable `AuditStore` when their domain
   tickets (#5, #6, later) land — no store change required.
3. **Actor resolution server-side**: each Activity API event carries
   `{id, name, kind}` for the acting paired client. `"system"` and `"cli"`
   stay literal strings. Unknown client ids fall back to the literal actor
   string. Resolution works for revoked clients (accountability preserved).
4. **Ordering & paging**: newest-first. `GET /api/activity?limit=&before_id=`
   pages backward through history with an exclusive `before_id` cursor (the
   `audit_events.id` primary key). Response carries `next_cursor` = last event's
   id when the page is full, else null.
5. **Append-only**: `AuditStore` offers only `append` and `list_recent`; no
   update/delete path exists on `audit_events`. The DB row is immutable once
   committed.
6. **Auth**: Activity API sits behind `get_current_client`, same as every other
   `/api` business route. Both paired kinds (device + browser) have equal
   read access.

## Domain model

`AuditEvent` (`dojo/model.py`) gains `id: int = 0` — the stable monotonic
cursor. It is populated by the store on write (DB autoincrement PK in
Postgres; sequential counter in `InMemoryStore`). Frozen and append-only.

New model:

- `ActivityEntry`: `id`, `action`, `occurred_at`, `details`,
  `actor: Client | str` — the resolved paired client, or a literal string
  (`"system"`, `"cli"`, or an unresolvable actor id).
- `ActivityPage`: `entries: list[ActivityEntry]`, `next_cursor: int | None`.

## Storage

No schema migration. `audit_events` already has:

- `id` integer PK (`autoincrement`) — the cursor,
- `action`, `actor`, `occurred_at`, `details` (JSON).

`AuditStore` (`dojo/ports.py`) contract changes:

- `list_recent(limit: int = 50, before_id: int | None = None) -> list[AuditEvent]`
  — newest-first, `before_id` exclusive.

`PostgresStore` runs `WHERE id < before_id ORDER BY id DESC LIMIT n`;
`InMemoryStore` mirrors the same semantics over its in-memory list.
Both already assign the row id on `append`.

## Ports (`dojo/ports.py`)

- `AuditStore(Protocol)`: `append(event)`; `list_recent(limit, before_id)`.
- Reuse `PairingStore.find_client_by_id` for actor resolution.

## Facade (`dojo/activity.py`)

`DojoActivity(audit: AuditStore, pairing: PairingStore)`:

- `list_activity(*, limit: int = 50, before_id: int | None = None) -> ActivityPage`
  — reads `audit.list_recent`, resolves each actor through
  `pairing.find_client_by_id` (string that parses as an int and matches a
  client → `Client`; else literal string), returns entries + `next_cursor`.

### Rules

- `limit` clamped to `1..100` (default 50).
- `next_cursor` is the last returned event's `id` when the page is full
  (`len(entries) == limit`), else `None`.
- Resolution order: actor string equal to `"system"` or `"cli"` → literal;
  parseable int and `find_client_by_id` hits → `Client`; otherwise literal.
- No role checks (equal permissions).

## FastAPI integration

New router `backend/routes/activity.py` under `/api/activity`:

- `GET /api/activity?limit=50&before_id=<id>` — auth required (route-level
  `Depends(get_current_client)`). Response:

```json
{
  "events": [
    {
      "id": 7,
      "action": "pairing.client_revoked",
      "occurred_at": "2026-08-12T12:00:00Z",
      "actor": {"id": 2, "name": "Phone", "kind": "device"},
      "details": {"client_id": 1}
    }
  ],
  "next_cursor": null
}
```

`create_app` builds `DojoActivity` from the shared store and exposes it as
`app.state.activity`; the router reads it via request state. Pydantic model
`ActivityEventOut` mirrors `ActivityEntry` (actor as a union of `ClientOut` and
`str`).

## Actor threading for current actions

- `DojoPublishing.ensure_active_package()` gains a `requester: str | None`
  parameter. The HTTP route `POST /api/packages/active` passes the authenticated
  client id; the scheduler path keeps `None` → `actor="system"`.
- Pairing events keep their existing actors (code creator / revoker / `"cli"`).

## Exceptions

No new exception types. Unknown/bad `limit` handled by FastAPI validation
(`Query(ge=1, le=100)`).

## Testing

### Domain (`dojo-core/tests/test_activity.py`, in-memory + real Postgres)

1. Newest-first order: two events appended → newest returned first.
2. Cursor paging: `before_id` returns strictly older events, no overlap between
   pages, `next_cursor` correct on full vs partial pages.
3. Actor resolution: paired client id string → `Client{id,name,kind}`;
   `"system"`/`"cli"` stay literal; unknown id stays literal.
4. Actor resolution works for a revoked client (still names the actor).
5. `limit` clamping.
6. Paged read against real Postgres (`pg_store`).

### Store (`dojo-core/tests/test_db_adapter.py`, `test_store_activity.py`)

- `list_recent` newest-first ordering.
- `before_id` excludes the cursor row and orders descending.
- `InMemoryStore` matches Postgres semantics.

### Contract (`backend/tests/test_api.py`, TestClient + in-memory stores)

- `GET /api/activity` unauthenticated → `401`.
- Paired device sees its own pairing + package actions with resolved `actor`.
- Browser session sees the same feed (equal privilege).
- `?before_id=` returns an older page; `next_cursor` null when exhausted.
- `POST /api/packages/active` audits `package.created` with the acting client.

Existing audit-order assertions in `test_db_adapter.py` update to the new
newest-first contract.

## Out of scope

- Emitting the remaining audit facts (destructive overwrite, review resolution,
  state transitions, Meta identifiers, recovery, consent) — their domain actions
  ship in later tickets; they reuse this store untouched.
- Android/web activity feed UIs (tickets #38, #31).
- Actor threading across media/edit/review/publish actions not yet built.