# Audit History and Activity Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the immutable audit/activity substructure and an Activity API: `AuditEvent` gains a stable id, the `AuditStore` reads are newest-first with an exclusive `before_id` cursor, a new `DojoActivity` facade resolves the acting paired client for display, the backend exposes `GET /api/activity`, and `package.created` is attributed to the acting client.

**Architecture:** A new `DojoActivity` deep facade in `dojo-core` (`dojo/activity.py`) owns the activity read path — newest-first ordering, cursor paging, server-side actor resolution — against the shared `AuditStore` and `PairingStore`. `AuditEvent.id` becomes the monotonic cursor (DB PK in Postgres, sequential counter in memory). `DojoPublishing.ensure_active_package` gains an optional `requester` so the HTTP route can attribute the action. FastAPI wires a thin `routes/activity.py` guarded by `get_current_client`, same as every other business route.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy 2.0, pytest, testcontainers-python, ruff, mypy.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md`; do not invent new domain nouns beyond the audit/activity vocabulary in the design doc.
- Audit is immutable and append-only: `AuditStore` exposes only `append` and `list_recent`; never add update/delete paths to `audit_events`.
- `AuditEvent` construction sites already use keyword args (`action=`, `actor=`, `occurred_at=`, `details=`); add `id` as the last field with default `0` so existing calls keep working.
- `list_recent` contract is **newest-first** with an **exclusive** `before_id` cursor. `before_id=None` means "from the newest end".
- `DojoActivity.list_activity` clamps `limit` to `1..100` (default 50); `next_cursor` is the last returned event's id when the page is full (`len(entries) == limit`), else `None`.
- Actor resolution: actor string `"system"` or `"cli"` → literal string; int-parseable and `find_client_by_id` hits → `Client` (including revoked clients); anything else → literal string.
- Activity API is equal-privilege: any paired device or browser reads it. Unauthenticated → `401`.
- Docstrings use pairing/client vocabulary already in the codebase (`client`, `device`, `browser`, `pairing code`).
- Lint: ruff (`E,F,I,UP`). dojo-core mypy with `disallow_untyped_defs`; backend mypy `strict`. Both must pass before each task's commit.
- Commands run from repo root. Tests against real Postgres via the `pg_store` fixture (testcontainers) use FakeClock for deterministic time.
- Every Python task: run the focused test file first, then the package's full suite, before committing.

---

### Task 1: Store contract — `AuditEvent.id` + newest-first `list_recent(before_id)`

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/ports.py`
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Modify: `dojo-core/src/dojo/adapters/memory.py`
- Create: `dojo-core/tests/test_store_activity.py`
- Modify: `dojo-core/tests/test_db_adapter.py`

**Interfaces:**
- Consumes: existing `AuditEvent`, `AuditStore` table row `AuditRow` (already has `id` PK).
- Produces: `AuditEvent(..., id: int = 0)` with `id` population by both stores; `AuditStore.list_recent(limit: int = 50, before_id: int | None = None) -> list[AuditEvent]` newest-first; `InMemoryStore.append` assigns sequential ids.

- [ ] **Step 1: Write the failing tests**

Append to `dojo-core/tests/test_store_activity.py`:
```python
from __future__ import annotations

from dojo.adapters.memory import InMemoryStore
from dojo.model import AuditEvent
from dojo.testing import FIXED_AT


def append(store: InMemoryStore, i: int) -> None:
    store.append(
        AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={"i": i})
    )


def test_memory_assigns_ids_newest_first() -> None:
    store = InMemoryStore()
    append(store, 1)
    append(store, 2)
    assert [(e.id, e.details) for e in store.list_recent()] == [(2, {"i": 2}), (1, {"i": 1})]


def test_memory_before_id_excludes_cursor_and_pages() -> None:
    store = InMemoryStore()
    for i in range(5):
        append(store, i)
    assert [e.id for e in store.list_recent(limit=10, before_id=4)] == [3, 2, 1]
    assert [e.id for e in store.list_recent(limit=2)] == [5, 4]
    assert [e.id for e in store.list_recent(limit=2, before_id=5)] == [4, 3]


def test_memory_limit_respected() -> None:
    store = InMemoryStore()
    for i in range(5):
        append(store, i)
    assert len(store.list_recent(limit=2)) == 2
```

Replace `test_append_and_list_recent` in `dojo-core/tests/test_db_adapter.py` with:
```python
def test_append_and_list_recent_newest_first(pg_store: PostgresStore) -> None:
    pg_store.append(
        AuditEvent(action="package.created", actor="system", occurred_at=FIXED_AT, details={"a": 1})
    )
    pg_store.append(
        AuditEvent(action="package.created", actor="system", occurred_at=FIXED_AT, details={"b": 2})
    )

    events = pg_store.list_recent()
    assert [e.details for e in events] == [{"b": 2}, {"a": 1}]
    assert [r.id for r in events] == [2, 1]


def test_list_recent_before_id_excludes_cursor(pg_store: PostgresStore) -> None:
    for i in range(5):
        pg_store.append(
            AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={"i": i})
        )
    events = pg_store.list_recent(limit=10, before_id=4)
    assert [e.id for e in events] == [3, 2, 1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_activity.py dojo-core/tests/test_db_adapter.py -v`
Expected: FAIL — `AuditEvent()` missing field `id`; memory events append with `id=0`; DB `list_recent` returns chronological order and has no `before_id`.

- [ ] **Step 3: Add `id` to `AuditEvent`**

In `dojo-core/src/dojo/model.py`, change `AuditEvent` to:
```python
@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor: str
    occurred_at: datetime
    details: dict = field(default_factory=dict)
    id: int = 0
```

- [ ] **Step 4: Update the `AuditStore` port**

In `dojo-core/src/dojo/ports.py`, replace `AuditStore` with:
```python
@runtime_checkable
class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list_recent(
        self, limit: int = 50, before_id: int | None = None
    ) -> list[AuditEvent]: ...
```

- [ ] **Step 5: Update `PostgresStore.list_recent`**

In `dojo-core/src/dojo/adapters/db.py`, replace `list_recent` with:
```python
    def list_recent(self, limit: int = 50, before_id: int | None = None) -> list[AuditEvent]:
        with self._session() as session:
            stmt = select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
            if before_id is not None:
                stmt = stmt.where(AuditRow.id < before_id)
            rows = session.scalars(stmt).all()
            return [
                AuditEvent(
                    id=r.id,
                    action=r.action,
                    actor=r.actor,
                    occurred_at=r.occurred_at,
                    details=r.details,
                )
                for r in rows
            ]
```

- [ ] **Step 6: Update `InMemoryStore`**

In `dojo-core/src/dojo/adapters/memory.py`:
- add `self._next_event_id = 1` to `__init__`,
- replace `append` and `list_recent`:
```python
    def append(self, event: AuditEvent) -> None:
        stored = replace(event, id=self._next_event_id)
        self._next_event_id += 1
        self._events.append(stored)

    def list_recent(self, limit: int = 50, before_id: int | None = None) -> list[AuditEvent]:
        events = self._events
        if before_id is not None:
            events = [e for e in events if e.id < before_id]
        return list(reversed(events[-limit:]))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_activity.py dojo-core/tests/test_db_adapter.py -v`
Expected: PASS (memory tests + updated DB tests; the truncated `test_list_recent_respects_limit` still passes against the new contract)

- [ ] **Step 8: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass (check nothing else asserts old chronological audit order — grep `list_recent`/`list_audit` usages)

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/ports.py dojo-core/src/dojo/adapters/db.py dojo-core/src/dojo/adapters/memory.py dojo-core/tests/test_store_activity.py dojo-core/tests/test_db_adapter.py
git commit -m "feat(dojo-core): stable audit ids and newest-first cursor reads (#4)"
```

---

### Task 2: `DojoActivity` facade — paging and actor resolution

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Create: `dojo-core/src/dojo/activity.py`
- Modify: `dojo-core/src/dojo/__init__.py`
- Create: `dojo-core/tests/test_activity.py`

**Interfaces:**
- Consumes: `AuditStore.list_recent(limit, before_id)`, `PairingStore.find_client_by_id(client_id) -> Client | None` (Task 1 + pairing from #3), `AuditEvent` with `id`.
- Produces: `ActivityEntry(id:int, action:str, occurred_at:datetime, details:dict, actor:Client|str)`; `ActivityPage(entries:list[ActivityEntry], next_cursor:int|None)`; `DojoActivity(audit: AuditStore, pairing: PairingStore)` with `list_activity(*, limit:int=50, before_id:int|None=None) -> ActivityPage`. Exports `ActivityEntry`, `ActivityPage`, `DojoActivity` from `dojo`.

- [ ] **Step 1: Write the failing tests**

`dojo-core/tests/test_activity.py`:
```python
from __future__ import annotations

from dojo import DojoActivity, DojoPairing
from dojo.adapters.memory import InMemoryStore
from dojo.model import AuditEvent, ActivityPage, Client
from dojo.testing import FIXED_AT, FakeClock


def make_system() -> tuple[InMemoryStore, DojoPairing, DojoActivity]:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    activity = DojoActivity(audit=store, pairing=store)
    return store, pairing, activity


def test_newest_first_with_ids() -> None:
    store, pairing, activity = make_system()
    pairing.create_pairing_code(requester="cli")
    page = activity.list_activity()
    assert isinstance(page, ActivityPage)
    assert [e.action for e in page.entries] == ["pairing.code_created"]
    assert page.entries[0].id >= 1


def test_pairs_and_revokes_page_newest_first_no_overlap() -> None:
    store, pairing, activity = make_system()
    issued = pairing.create_pairing_code(requester="cli")
    result = pairing.validate_code(code=issued.raw_code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester=str(result.client_id))

    first = activity.list_activity(limit=1)
    assert first.next_cursor is not None
    second = activity.list_activity(limit=1, before_id=first.next_cursor)
    third = activity.list_activity(limit=1, before_id=second.next_cursor)

    ids = [e.id for e in first.entries + second.entries + third.entries]
    assert len(ids) == len(set(ids)) == 3
    assert all(a > b for a, b in zip(ids, ids[1:]))


def test_actor_resolved_to_revoked_client() -> None:
    store, pairing, activity = make_system()
    issued = pairing.create_pairing_code(requester="cli")
    result = pairing.validate_code(code=issued.raw_code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester=str(result.client_id))

    page = activity.list_activity()
    revoked = next(e for e in page.entries if e.action == "pairing.client_revoked")
    assert isinstance(revoked.actor, Client)
    assert revoked.actor.id == result.client_id
    assert revoked.actor.name == "Phone"
    assert revoked.actor.kind == "device"


def test_cli_actors_stay_literal() -> None:
    store, pairing, activity = make_system()
    issued = pairing.create_pairing_code(requester="cli")
    page = activity.list_activity()
    assert all(e.actor == "cli" for e in page.entries)


def test_unknown_and_nonnumeric_actors_stay_literal() -> None:
    store, pairing, activity = make_system()
    store.append(AuditEvent(action="x", actor="999", occurred_at=FIXED_AT, details={}))
    store.append(AuditEvent(action="x", actor="not-a-client", occurred_at=FIXED_AT, details={}))
    actors = [e.actor for e in activity.list_activity() if e.action == "x"]
    assert actors == ["not-a-client", "999"]


def test_system_actor_stays_literal() -> None:
    store, pairing, activity = make_system()
    store.append(AuditEvent(action="package.created", actor="system", occurred_at=FIXED_AT, details={}))
    created = next(e for e in activity.list_activity() if e.action == "package.created")
    assert created.actor == "system"


def test_limit_clamped_to_100() -> None:
    store, pairing, activity = make_system()
    for _ in range(10):
        store.append(AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={}))
    assert len(activity.list_activity(limit=0).entries) == 1
    assert len(activity.list_activity(limit=999).entries) == 10


def test_next_cursor_null_when_page_partial() -> None:
    store, pairing, activity = make_system()
    store.append(AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={}))
    page = activity.list_activity(limit=50)
    assert len(page.entries) == 1
    assert page.next_cursor is None


def test_activity_over_postgres(pg_store) -> None:
    pairing = DojoPairing(pairing=pg_store, audit=pg_store, clock=FakeClock())
    activity = DojoActivity(audit=pg_store, pairing=pg_store)

    issued = pairing.create_pairing_code(requester="cli")
    result = pairing.validate_code(code=issued.raw_code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester=str(result.client_id))

    first = activity.list_activity(limit=1)
    assert first.next_cursor is not None
    assert first.entries[0].action == "pairing.client_revoked"
    second = activity.list_activity(limit=1, before_id=first.next_cursor)
    assert second.entries[0].action == "pairing.client_paired"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_activity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dojo.activity'`.

- [ ] **Step 3: Add `ActivityEntry` and `ActivityPage` models**

Append to `dojo-core/src/dojo/model.py` (after `PairingResult`):
```python
@dataclass(frozen=True)
class ActivityEntry:
    id: int
    action: str
    occurred_at: datetime
    details: dict
    actor: Client | str


@dataclass(frozen=True)
class ActivityPage:
    entries: list[ActivityEntry]
    next_cursor: int | None
```
`Client` is already defined above in the same module (`from __future__ import annotations` makes the forward reference valid).

- [ ] **Step 4: Write the facade**

`dojo-core/src/dojo/activity.py`:
```python
from __future__ import annotations

from dojo.model import ActivityEntry, ActivityPage, AuditEvent, Client
from dojo.ports import AuditStore, PairingStore

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
LITERAL_ACTORS = frozenset({"system", "cli"})


class DojoActivity:
    """Deep behavioral seam for the audit/activity read path.

    Owns newest-first ordering, exclusive-before-id cursor paging, and
    server-side actor resolution from the free-string actor to the paired
    Client responsible. Domain actions write through both DojoPublishing and
    DojoPairing; this facade is the only read surface.
    """

    def __init__(self, *, audit: AuditStore, pairing: PairingStore) -> None:
        self._audit = audit
        self._pairing = pairing

    def list_activity(
        self, *, limit: int = DEFAULT_LIMIT, before_id: int | None = None
    ) -> ActivityPage:
        limit = max(1, min(MAX_LIMIT, limit))
        events = self._audit.list_recent(limit=limit, before_id=before_id)
        entries = [
            ActivityEntry(
                id=e.id,
                action=e.action,
                occurred_at=e.occurred_at,
                details=e.details,
                actor=self._resolve_actor(e),
            )
            for e in events
        ]
        next_cursor = entries[-1].id if len(entries) == limit else None
        return ActivityPage(entries=entries, next_cursor=next_cursor)

    def _resolve_actor(self, event: AuditEvent) -> Client | str:
        actor = event.actor
        if actor in LITERAL_ACTORS:
            return actor
        try:
            client_id = int(actor)
        except ValueError:
            return actor
        client = self._pairing.find_client_by_id(client_id)
        return client if client is not None else actor
```

- [ ] **Step 5: Export from `dojo`**

In `dojo-core/src/dojo/__init__.py`:
- add `from dojo.activity import DojoActivity` after the pairing import,
- add `ActivityEntry`, `ActivityPage` to the `from dojo.model import (...)` block,
- add `"ActivityEntry"`, `"ActivityPage"`, `"DojoActivity"` to `__all__`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_activity.py -v`
Expected: PASS (9 passed, including the real-Postgres paging test via `pg_store`)

- [ ] **Step 7: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/activity.py dojo-core/src/dojo/__init__.py dojo-core/tests/test_activity.py
git commit -m "feat(dojo-core): activity facade with cursor paging and actor resolution (#4)"
```

---

### Task 3: Attribute `package.created` to the acting client

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Modify: `backend/src/backend/routes/packages.py`
- Modify: `dojo-core/tests/test_publishing.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `DojoPublishing` facade (audit actor currently `"system"`).
- Produces: `DojoPublishing.ensure_active_package(*, requester: str | None = None) -> Package`; HTTP route passes `requester=str(<client id>)`; audit event `package.created` actor = `requester` or `"system"`.

- [ ] **Step 1: Write the failing tests**

Append to `dojo-core/tests/test_publishing.py`:
```python
def test_ensure_active_package_attributed_to_requester(tmp_path):
    store, seam = make_seam(tmp_path)

    package = seam.ensure_active_package(requester="7")

    assert package.status == "active"
    events = seam.list_audit()
    assert events[0].actor == "7"
```

- [ ] **Step 2: Run dojo-core tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v`
Expected: FAIL — `ensure_active_package() got an unexpected keyword argument 'requester'`.

- [ ] **Step 3: Add the `requester` parameter**

In `dojo-core/src/dojo/publishing.py`, change the signature and audit write:
```python
    def ensure_active_package(self, *, requester: str | None = None) -> Package:
        """Create an active Dojo Paylaşım Paketi when none exists."""
```
and replace the audit append actor with:
```python
        self._audit.append(
            AuditEvent(
                action="package.created",
                actor=requester or "system",
                occurred_at=now,
                details={"folder_name": folder_name},
            )
        )
```

- [ ] **Step 4: Run dojo-core tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_publishing.py -v`
Expected: PASS (new attribution test + existing ones; existing tests call `ensure_active_package()` with no args → actor stays `"system"`, `test_ensure_active_package_creates_folder_manifest_row_and_audit` still asserts details only)

- [ ] **Step 5: Pass the requester from the HTTP route**

In `backend/src/backend/routes/packages.py`, update imports and the `ensure_active` endpoint:
```python
from dojo import ActivePackageExists, Client, DojoPublishing
from backend.deps import get_current_client
```
```python
@router.post("/active", response_model=PackageOut, status_code=201)
def ensure_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.ensure_active_package(requester=str(client.id))
    except ActivePackageExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)
```

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass
Run backend related commands (the new API test will fail until Task 4 lands; run without it to confirm nothing else broke):
`uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings

```bash
git add dojo-core/src/dojo/publishing.py backend/src/backend/routes/packages.py dojo-core/tests/test_publishing.py
git commit -m "feat(dojo-core,backend): attribute package creation to the acting client (#4)"
```

---

### Task 4: Activity API route and wiring

**Files:**
- Create: `backend/src/backend/routes/activity.py`
- Modify: `backend/src/backend/deps.py`
- Modify: `backend/src/backend/main.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `DojoActivity.list_activity(*)` (Task 2), `get_current_client` (from #3), `ActivityEntry.actor: Client | str`.
- Produces: `backend.routes.activity.router` with `GET /api/activity?limit=50&before_id=<id>`; response `{events: [ActivityEventOut], next_cursor: int | None}`; `backend.deps.build_activity() -> DojoActivity`; `app.state.activity`; include router under `get_current_client`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:
```python
from fastapi.testclient import TestClient
from dojo import DojoActivity


def test_activity_requires_auth(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.get("/api/activity").status_code == 401


def test_paired_device_sees_resolved_activity(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    events = client.get("/api/activity", headers=bearer(token)).json()["events"]
    actions = [e["action"] for e in events]
    assert "package.created" in actions
    assert "pairing.client_paired" in actions
    created = next(e for e in events if e["action"] == "package.created")
    assert created["actor"]["kind"] == "device"
    assert created["actor"]["name"] == "Phone"
    assert created["actor"]["id"] == client.get("/api/pairing/me", headers=bearer(token)).json()["id"]


def test_activity_cursor_pages_no_overlap(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    first = client.get(
        "/api/activity", headers=bearer(token), params={"limit": 1}
    ).json()
    assert len(first["events"]) == 1
    assert first["next_cursor"] is not None

    second = client.get(
        "/api/activity",
        headers=bearer(token),
        params={"limit": 1, "before_id": first["next_cursor"]},
    ).json()
    assert second["events"]
    ids = [e["id"] for e in first["events"]] + [e["id"] for e in second["events"]]
    assert len(set(ids)) == 2
    assert first["events"][0]["id"] > second["events"][0]["id"]


def test_browser_session_sees_activity(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    paired = client.post(
        "/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"}
    )
    assert paired.status_code == 200
    assert client.get("/api/activity").json()["events"]
```

Update `make_app` in `backend/tests/test_api.py` to wire `DojoActivity`:
```python
def make_app(tmp_path: Path) -> tuple[TestClient, DojoPublishing, DojoPairing]:
    store = InMemoryStore()
    publishing = DojoPublishing(
        packages=store,
        audit=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=StubNotifier(),
        signed_urls=StubSignedUrlStore(),
    )
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    activity = DojoActivity(audit=store, pairing=store)
    client = TestClient(create_app(publishing, pairing, activity, cookie_secure=False))
    return client, publishing, pairing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.routes.activity'` (and `create_app` rejects the extra positional arg).

- [ ] **Step 3: Add the dependency builder**

In `backend/src/backend/deps.py`, add `DojoActivity` to the `dojo` import and append:
```python
def build_activity() -> DojoActivity:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoActivity(audit=store, pairing=store)
```

- [ ] **Step 4: Add the router**

`backend/src/backend/routes/activity.py`:
```python
from __future__ import annotations

from datetime import datetime

from dojo import Client, DojoActivity
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_activity(request: Request) -> DojoActivity:
    return request.app.state.activity


class ClientRefOut(BaseModel):
    id: int
    name: str
    kind: str


class ActivityEventOut(BaseModel):
    id: int
    action: str
    occurred_at: datetime
    details: dict
    actor: ClientRefOut | str


class ActivityPageOut(BaseModel):
    events: list[ActivityEventOut]
    next_cursor: int | None


router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=ActivityPageOut)
def list_activity(
    activity: DojoActivity = Depends(get_activity),
    limit: int = Query(50, ge=1, le=100),
    before_id: int | None = Query(None),
) -> ActivityPageOut:
    page = activity.list_activity(limit=limit, before_id=before_id)
    events = [
        ActivityEventOut(
            id=e.id,
            action=e.action,
            occurred_at=e.occurred_at,
            details=e.details,
            actor=(
                e.actor
                if isinstance(e.actor, str)
                else ClientRefOut(id=e.actor.id, name=e.actor.name, kind=e.actor.kind)
            ),
        )
        for e in page.entries
    ]
    return ActivityPageOut(events=events, next_cursor=page.next_cursor)
```

- [ ] **Step 5: Wire into the app**

In `backend/src/backend/main.py`:
- imports: add `from dojo import DojoActivity, DojoPairing, DojoPublishing`, `from backend.deps import build_activity, build_pairing, build_publishing, get_current_client`, `from backend.routes import activity as activity_router`,
- `lifespan`: after the pairing block add:
```python
    if not hasattr(app.state, "activity"):
        app.state.activity = build_activity()
```
- `create_app` signature: `def create_app(publishing=None, pairing=None, activity=None, cookie_secure=None)`; after the `pairing` block add:
```python
    if activity is not None:
        app.state.activity = activity
```
- include the router after the pairing include:
```python
    app.include_router(activity_router.router, dependencies=[Depends(get_current_client)])
```

- [ ] **Step 6: Run backend tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py backend/tests/test_cli.py -v`
Expected: PASS (activity tests + Task 3's `test_package_created_audited_with_acting_client`)

- [ ] **Step 7: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/activity.py backend/src/backend/deps.py backend/src/backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): activity API with resolved actors and cursor paging (#4)"
```

---

### Task 5: Full suite, design-vs-implementation check, close out

- [ ] **Step 1: Run both full suites**

Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

- [ ] **Step 2: Lint and typecheck everything**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings

- [ ] **Step 3: Verify acceptance criteria against the design**

Check the spec (`docs/superpowers/specs/2026-08-12-audit-history-and-activity-feed-design.md`):
- immutable append-only audit with timestamp + acting paired client → AuditStore has no update/delete; `DojoActivity._resolve_actor` returns the Client; `package.created` threaded through `requester`.
- required audit facts observable → pairing events already emitted; remainder arrives via the same store in later tickets (documented out of scope).
- recent activity retrievable for display → `GET /api/activity` for both client kinds (Task 4 tests).

- [ ] **Step 4: Commit any stragglers and note the follow-up**

No new files expected beyond Tasks 1-4. If a stray file exists, commit it. Do not close issue #4 — implementation completion is reported by the implementer, and closing is handled separately after /code-review.