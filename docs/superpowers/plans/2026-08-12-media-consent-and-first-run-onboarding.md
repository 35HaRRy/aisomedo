# Media-Consent Policy and First-Run Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the media-consent policy substructure and first-run onboarding state: an installation-wide consent policy (version + text) settable via CLI, one idempotent acceptance per policy version, a derived `pairing`/`consent` setup checklist, a Setup API under `/api/setup`, and a `dojo-consent set-policy` CLI.

**Architecture:** A new `DojoSetup` deep facade in `dojo-core` (`dojo/setup.py`) owns the policy lifecycle, per-version acceptance recording, the derived onboarding checklist, and the `is_ready` scheduling gate, against the new `SetupStore` and the existing `PairingStore`/`AuditStore`. FastAPI wires a thin `routes/setup.py` guarded by `get_current_client`, same as every other business route; `backend/cli.py` gains `dojo-consent set-policy`.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy 2.0, alembic, pytest, testcontainers-python, ruff, mypy.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md`; do not invent new domain nouns beyond the consent/onboarding vocabulary in the design doc.
- Consent policy is **installation-wide**: one current policy = highest `version`; one `ConsentAcceptance` row per `policy_version` (unique), inherited by every client. No per-client consent rows.
- Acceptance recording is **idempotent**: a version that already has an acceptance returns the existing record — no duplicate row, no duplicate `consent.accepted` audit event.
- `set_policy` rejects a `version` lower than the current max (`ConsentPolicyDowngrade`); same-version re-set updates text in place.
- `checklist()` is **derived, not stored**: `pairing` complete ⟺ any non-revoked client exists; `consent` complete ⟺ current policy version has an acceptance.
- Audit events `consent.policy_updated` and `consent.accepted` attribute the acting client (`str(client.id)` from routes, `"cli"` from the CLI).
- Setup API is equal-privilege: any paired device or browser reads/accepts it. Unauthenticated → `401`. Consent API returns `404` when no policy is configured.
- Lint: ruff (`E,F,I,UP`). dojo-core mypy with `disallow_untyped_defs`; backend mypy `strict`. Both must pass before each task's commit.
- Commands run from repo root. Tests against real Postgres via the `pg_store` fixture (testcontainers) use `FakeClock` for deterministic time.
- Every Python task: run the focused test file first, then the package's full suite, before committing.
- `conftest.py` TRUNCATE list must include the two new tables (`consent_policies`, `consent_acceptances`).

---

### Task 1: Storage — models, `SetupStore` port, migration, both store adapters

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/ports.py`
- Modify: `dojo-core/src/dojo/exceptions.py`
- Create: `dojo-core/migrations/versions/0003_setup.py`
- Modify: `dojo-core/src/dojo/adapters/memory.py`
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Create: `dojo-core/tests/test_store_setup.py`
- Modify: `dojo-core/tests/conftest.py`
- Modify: `dojo-core/tests/test_db_adapter.py`

**Interfaces:**
- Consumes: existing `InMemoryStore`/`PostgresStore`, `Base`, alembic conventions from `0002_pairing`.
- Produces:
  - `ConsentPolicy(version:int, text:str, created_at:datetime, created_by:str, id:int=0)`
  - `ConsentAcceptance(policy_version:int, accepted_at:datetime, accepting_client_id:int, accepting_client_name:str, accepting_client_kind:str, id:int=0)`
  - `SetupStore` protocol with `create_policy(*, version, text, created_by, created_at) -> ConsentPolicy`, `get_current_policy() -> ConsentPolicy | None`, `get_policy(version:int) -> ConsentPolicy | None`, `find_acceptance(policy_version:int) -> ConsentAcceptance | None`, `record_acceptance(acceptance: ConsentAcceptance) -> bool`
  - `ConsentError(DojoError)` base; `ConsentPolicyDowngrade(ConsentError)`, `NoConsentPolicy(ConsentError)`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_store_setup.py`:
```python
from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import ConsentAcceptance
from dojo.testing import FIXED_AT


def make_acceptance(*, version: int = 1) -> ConsentAcceptance:
    return ConsentAcceptance(
        policy_version=version,
        accepted_at=FIXED_AT,
        accepting_client_id=7,
        accepting_client_name="Phone",
        accepting_client_kind="device",
    )


def test_memory_policy_roundtrip_and_in_place_update() -> None:
    store = InMemoryStore()
    store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    store.create_policy(version=1, text="v1b", created_by="cli", created_at=FIXED_AT)
    found = store.get_policy(1)
    assert found is not None
    assert found.text == "v1b"
    assert found.created_by == "cli"


def test_memory_get_current_policy_returns_highest_version() -> None:
    store = InMemoryStore()
    store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    store.create_policy(version=3, text="v3", created_by="cli", created_at=FIXED_AT)
    current = store.get_current_policy()
    assert current is not None
    assert current.version == 3
    assert store.get_policy(2) is None


def test_memory_acceptance_idempotent() -> None:
    store = InMemoryStore()
    assert store.record_acceptance(make_acceptance()) is True
    assert store.record_acceptance(make_acceptance()) is False
    found = store.find_acceptance(1)
    assert found is not None
    assert found.accepting_client_id == 7
    assert store.find_acceptance(9) is None


def test_pg_policy_roundtrip_and_in_place_update(pg_store: PostgresStore) -> None:
    pg_store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    pg_store.create_policy(version=1, text="v1b", created_by="cli", created_at=FIXED_AT)
    found = pg_store.get_policy(1)
    assert found is not None
    assert found.text == "v1b"


def test_pg_get_current_policy_returns_highest_version(pg_store: PostgresStore) -> None:
    pg_store.create_policy(version=1, text="v1", created_by="cli", created_at=FIXED_AT)
    pg_store.create_policy(version=3, text="v3", created_by="cli", created_at=FIXED_AT)
    current = pg_store.get_current_policy()
    assert current is not None
    assert current.version == 3


def test_pg_acceptance_idempotent(pg_store: PostgresStore) -> None:
    assert pg_store.record_acceptance(make_acceptance()) is True
    assert pg_store.record_acceptance(make_acceptance()) is False
    found = pg_store.find_acceptance(1)
    assert found is not None
    assert found.accepting_client_id == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_setup.py -v`
Expected: FAIL — `ConsentAcceptance` undefined and store methods missing (`create_policy`, `get_current_policy`, etc.).

- [ ] **Step 3: Add the domain models**

In `dojo-core/src/dojo/model.py`, append (after `ActivityPage`):
```python
@dataclass(frozen=True)
class ConsentPolicy:
    version: int
    text: str
    created_at: datetime
    created_by: str
    id: int = 0


@dataclass(frozen=True)
class ConsentAcceptance:
    policy_version: int
    accepted_at: datetime
    accepting_client_id: int
    accepting_client_name: str
    accepting_client_kind: str
    id: int = 0


@dataclass(frozen=True)
class SetupItem:
    key: str
    label: str
    complete: bool
```

- [ ] **Step 4: Add the exceptions**

In `dojo-core/src/dojo/exceptions.py`, append:
```python
class ConsentError(DojoError):
    pass


class ConsentPolicyDowngrade(ConsentError):
    pass


class NoConsentPolicy(ConsentError):
    pass
```

- [ ] **Step 5: Add the `SetupStore` port**

In `dojo-core/src/dojo/ports.py`, extend the `from dojo.model import ...` line to include `ConsentAcceptance, ConsentPolicy`, and append:
```python
@runtime_checkable
class SetupStore(Protocol):
    def create_policy(
        self, *, version: int, text: str, created_by: str, created_at: datetime
    ) -> ConsentPolicy: ...

    def get_current_policy(self) -> ConsentPolicy | None: ...
    def get_policy(self, version: int) -> ConsentPolicy | None: ...
    def find_acceptance(self, policy_version: int) -> ConsentAcceptance | None: ...
    def record_acceptance(self, acceptance: ConsentAcceptance) -> bool: ...
```

- [ ] **Step 6: Add the migration**

Create `dojo-core/migrations/versions/0003_setup.py`:
```python
"""consent_policies and consent_acceptances

Revision ID: 0003_setup
Revises: 0002_pairing
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_setup"
down_revision: Union[str, None] = "0002_pairing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consent_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=4096), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_consent_policies_version", "consent_policies", ["version"])
    op.create_table(
        "consent_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepting_client_id", sa.Integer(), nullable=False),
        sa.Column("accepting_client_name", sa.String(length=128), nullable=False),
        sa.Column("accepting_client_kind", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("policy_version"),
    )
    op.create_index(
        "ix_consent_acceptances_policy_version", "consent_acceptances", ["policy_version"]
    )


def downgrade() -> None:
    op.drop_index("ix_consent_acceptances_policy_version", table_name="consent_acceptances")
    op.drop_table("consent_acceptances")
    op.drop_index("ix_consent_policies_version", table_name="consent_policies")
    op.drop_table("consent_policies")
```

- [ ] **Step 7: Implement `InMemoryStore` methods**

In `dojo-core/src/dojo/adapters/memory.py`:
- extend the model import: `from dojo.model import AuditEvent, Client, ConsentAcceptance, ConsentPolicy, Package, PairingCode`
- add to `__init__`:
```python
        self._policies: list[ConsentPolicy] = []
        self._acceptances: list[ConsentAcceptance] = []
        self._next_policy_id = 1
        self._next_acceptance_id = 1
```
- append methods:
```python
    def create_policy(
        self, *, version: int, text: str, created_by: str, created_at: datetime
    ) -> ConsentPolicy:
        for i, existing in enumerate(self._policies):
            if existing.version == version:
                updated = replace(
                    existing,
                    text=text,
                    created_by=created_by,
                    created_at=created_at,
                )
                self._policies[i] = updated
                return updated
        created = ConsentPolicy(
            id=self._next_policy_id,
            version=version,
            text=text,
            created_by=created_by,
            created_at=created_at,
        )
        self._next_policy_id += 1
        self._policies.append(created)
        return created

    def get_current_policy(self) -> ConsentPolicy | None:
        return max(self._policies, key=lambda p: p.version, default=None)

    def get_policy(self, version: int) -> ConsentPolicy | None:
        return next((p for p in self._policies if p.version == version), None)

    def find_acceptance(self, policy_version: int) -> ConsentAcceptance | None:
        return next((a for a in self._acceptances if a.policy_version == policy_version), None)

    def record_acceptance(self, acceptance: ConsentAcceptance) -> bool:
        if any(a.policy_version == acceptance.policy_version for a in self._acceptances):
            return False
        created = replace(acceptance, id=self._next_acceptance_id)
        self._next_acceptance_id += 1
        self._acceptances.append(created)
        return True
```

- [ ] **Step 8: Implement `PostgresStore` methods**

In `dojo-core/src/dojo/adapters/db.py`:
- extend imports: `from sqlalchemy.dialects.postgresql import insert as pg_insert` and `from sqlalchemy.exc import IntegrityError`; extend model import to `AuditEvent, Client, ConsentAcceptance, ConsentPolicy, Package, PairingCode`.
- add rows after `ClientRow`:
```python
class ConsentPolicyRow(Base):
    __tablename__ = "consent_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(unique=True, nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(4096), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class ConsentAcceptanceRow(Base):
    __tablename__ = "consent_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    policy_version: Mapped[int] = mapped_column(unique=True, nullable=False, index=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepting_client_id: Mapped[int] = mapped_column(nullable=False)
    accepting_client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    accepting_client_kind: Mapped[str] = mapped_column(String(16), nullable=False)
```
- append methods to `PostgresStore`:
```python
    def create_policy(
        self, *, version: int, text: str, created_by: str, created_at: datetime
    ) -> ConsentPolicy:
        with self._session() as session:
            stmt = pg_insert(ConsentPolicyRow).values(
                version=version, text=text, created_at=created_at, created_by=created_by
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ConsentPolicyRow.version],
                set_={
                    "text": stmt.excluded.text,
                    "created_at": stmt.excluded.created_at,
                    "created_by": stmt.excluded.created_by,
                },
            )
            session.execute(stmt)
            session.commit()
            row = session.scalar(
                select(ConsentPolicyRow).where(ConsentPolicyRow.version == version)
            )
            assert row is not None
            return self._policy_from_row(row)

    def get_current_policy(self) -> ConsentPolicy | None:
        with self._session() as session:
            row = session.scalar(
                select(ConsentPolicyRow)
                .order_by(ConsentPolicyRow.version.desc())
                .limit(1)
            )
            return self._policy_from_row(row) if row is not None else None

    def get_policy(self, version: int) -> ConsentPolicy | None:
        with self._session() as session:
            row = session.scalar(
                select(ConsentPolicyRow).where(ConsentPolicyRow.version == version)
            )
            return self._policy_from_row(row) if row is not None else None

    def find_acceptance(self, policy_version: int) -> ConsentAcceptance | None:
        with self._session() as session:
            row = session.scalar(
                select(ConsentAcceptanceRow).where(
                    ConsentAcceptanceRow.policy_version == policy_version
                )
            )
            return self._acceptance_from_row(row) if row is not None else None

    def record_acceptance(self, acceptance: ConsentAcceptance) -> bool:
        with self._session() as session:
            try:
                session.add(
                    ConsentAcceptanceRow(
                        policy_version=acceptance.policy_version,
                        accepted_at=acceptance.accepted_at,
                        accepting_client_id=acceptance.accepting_client_id,
                        accepting_client_name=acceptance.accepting_client_name,
                        accepting_client_kind=acceptance.accepting_client_kind,
                    )
                )
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False
```
- append row-mapper helpers:
```python
    @staticmethod
    def _policy_from_row(row: ConsentPolicyRow) -> ConsentPolicy:
        return ConsentPolicy(
            id=row.id,
            version=row.version,
            text=row.text,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    @staticmethod
    def _acceptance_from_row(row: ConsentAcceptanceRow) -> ConsentAcceptance:
        return ConsentAcceptance(
            id=row.id,
            policy_version=row.policy_version,
            accepted_at=row.accepted_at,
            accepting_client_id=row.accepting_client_id,
            accepting_client_name=row.accepting_client_name,
            accepting_client_kind=row.accepting_client_kind,
        )
```

- [ ] **Step 9: Update test fixtures and migration test**

In `dojo-core/tests/conftest.py`, change the TRUNCATE statement to:
```python
            text("TRUNCATE TABLE consent_acceptances, consent_policies, pairing_codes, "
                 "clients, audit_events, packages RESTART IDENTITY")
```
In `dojo-core/tests/test_db_adapter.py`, extend the schema assertion in `test_alembic_upgrade_head_creates_schema`:
```python
    assert {"packages", "audit_events", "consent_policies", "consent_acceptances"} <= set(
        inspector.get_table_names()
    )
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_setup.py dojo-core/tests/test_db_adapter.py -v`
Expected: PASS (setup store tests + alembic upgrade creates the two new tables).

- [ ] **Step 11: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/ports.py dojo-core/src/dojo/exceptions.py dojo-core/migrations/versions/0003_setup.py dojo-core/src/dojo/adapters/memory.py dojo-core/src/dojo/adapters/db.py dojo-core/tests/test_store_setup.py dojo-core/tests/conftest.py dojo-core/tests/test_db_adapter.py
git commit -m "feat(dojo-core): consent policy and acceptance storage (#5)"
```

---

### Task 2: `DojoSetup` facade — policy lifecycle, acceptance, checklist, gate

**Files:**
- Create: `dojo-core/src/dojo/setup.py`
- Modify: `dojo-core/src/dojo/__init__.py`
- Create: `dojo-core/tests/test_setup.py`

**Interfaces:**
- Consumes: `SetupStore` (Task 1), `PairingStore.list_clients() -> list[Client]`, `AuditStore.append(AuditEvent)`, `Clock.now()`, models `ConsentPolicy`, `ConsentAcceptance`, `SetupItem`, `Client`, `AuditEvent`.
- Produces:
  - `DojoSetup(*, setup: SetupStore, audit: AuditStore, pairing: PairingStore, clock: Clock | None = None)`
  - `current_policy() -> ConsentPolicy | None`
  - `set_policy(*, version: int, text: str, requester: str) -> ConsentPolicy` (raises `ConsentPolicyDowngrade`)
  - `accept_current_policy(*, client: Client) -> ConsentAcceptance` (raises `NoConsentPolicy`; idempotent; audits the acceptance only when freshly recorded)
  - `current_acceptance() -> ConsentAcceptance | None`
  - `checklist() -> list[SetupItem]` — keys `"pairing"` and `"consent"`
  - `is_ready() -> bool`
- Exports from `dojo`: `DojoSetup`, `ConsentError`, `ConsentPolicy`, `ConsentAcceptance`, `SetupItem`, `ConsentPolicyDowngrade`, `NoConsentPolicy`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_setup.py`:
```python
from __future__ import annotations

import threading

import pytest
from dojo import ConsentPolicyDowngrade, DojoPairing, DojoSetup, NoConsentPolicy
from dojo.adapters.db import PostgresStore
from dojo.adapters.memory import InMemoryStore
from dojo.model import Client, ConsentAcceptance
from dojo.testing import FakeClock


def make_setup(store: InMemoryStore) -> DojoSetup:
    return DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())


def make_pairing(store: InMemoryStore) -> DojoPairing:
    return DojoPairing(pairing=store, audit=store, clock=FakeClock())


def add_client(setup: DojoSetup, store: InMemoryStore, *, name: str = "Phone") -> Client:
    pairing = make_pairing(store)
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name=name)
    client = store.find_client_by_id(result.client_id)
    assert client is not None
    return client


def test_set_policy_creates_current_policy_and_audits() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    policy = setup.set_policy(version=1, text="Riza metni", requester="cli")
    assert policy.version == 1
    assert policy.text == "Riza metni"
    assert setup.current_policy() == policy
    events = [e for e in store.list_recent() if e.action == "consent.policy_updated"]
    assert len(events) == 1
    assert events[0].actor == "cli"
    assert events[0].details["version"] == 1


def test_set_policy_same_version_updates_text_in_place() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=1, text="v1", requester="cli")
    setup.set_policy(version=1, text="v1b", requester="cli")
    policy = setup.current_policy()
    assert policy is not None and policy.text == "v1b"
    updated = [e for e in store.list_recent() if e.action == "consent.policy_updated"]
    assert len(updated) == 2


def test_set_policy_rejects_downgrade() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=3, text="v3", requester="cli")
    with pytest.raises(ConsentPolicyDowngrade):
        setup.set_policy(version=2, text="v2", requester="cli")


def test_accept_current_policy_records_once_and_is_idempotent() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=1, text="v1", requester="cli")
    client = add_client(setup, store)

    acceptance = setup.accept_current_policy(client=client)
    again = setup.accept_current_policy(client=client)

    assert isinstance(acceptance, ConsentAcceptance)
    assert acceptance.policy_version == 1
    assert acceptance.accepting_client_id == client.id
    assert acceptance.accepting_client_name == "Phone"
    assert acceptance.accepting_client_kind == "device"
    assert again == acceptance
    accepted = [e for e in store.list_recent() if e.action == "consent.accepted"]
    assert len(accepted) == 1
    assert accepted[0].actor == str(client.id)
    assert accepted[0].details["version"] == 1


def test_accept_without_policy_raises() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    client = add_client(setup, store)
    with pytest.raises(NoConsentPolicy):
        setup.accept_current_policy(client=client)


def test_new_version_requires_fresh_acceptance() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    setup.set_policy(version=1, text="v1", requester="cli")
    client = add_client(setup, store)
    setup.accept_current_policy(client=client)
    setup.set_policy(version=2, text="v2", requester="cli")
    assert setup.checklist_item("consent").complete is False
    setup.accept_current_policy(client=client)
    assert setup.checklist_item("consent").complete is True


def test_checklist_pairing_tracks_non_revoked_clients() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    assert setup.checklist_item("pairing").complete is False
    client = add_client(setup, store)
    assert setup.checklist_item("pairing").complete is True
    make_pairing(store).revoke_client(client_id=client.id, requester="cli")
    assert setup.checklist_item("pairing").complete is False


def test_checklist_consent_requires_current_version_accepted() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    add_client(setup, store)
    assert setup.checklist_item("consent").complete is False
    setup.set_policy(version=1, text="v1", requester="cli")
    assert setup.checklist_item("consent").complete is False
    client = add_client(setup, store)
    setup.accept_current_policy(client=client)
    assert setup.checklist_item("consent").complete is True


def test_is_ready_requires_all_items() -> None:
    store = InMemoryStore()
    setup = make_setup(store)
    assert setup.is_ready() is False
    add_client(setup, store)
    assert setup.is_ready() is False
    setup.set_policy(version=1, text="v1", requester="cli")
    client = store.find_client_by_id(1)
    assert client is not None
    setup.accept_current_policy(client=client)
    assert setup.is_ready() is True


def test_acceptance_over_postgres_once_per_version(pg_store: PostgresStore) -> None:
    setup = DojoSetup(setup=pg_store, audit=pg_store, pairing=pg_store, clock=FakeClock())
    pairing = DojoPairing(pairing=pg_store, audit=pg_store, clock=FakeClock())
    setup.set_policy(version=1, text="v1", requester="cli")
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")

    client = pg_store.find_client_by_id(result.client_id)
    assert client is not None
    setup.accept_current_policy(client=client)
    setup.accept_current_policy(client=client)

    sources = pg_store.find_acceptance(1)
    assert sources is not None
    events = pg_store.list_recent()
    accepted = [e for e in events if e.action == "consent.accepted"]
    assert len(accepted) == 1


def test_concurrent_acceptance_records_single_row(pg_store: PostgresStore) -> None:
    setup = DojoSetup(setup=pg_store, audit=pg_store, pairing=pg_store, clock=FakeClock())
    setup.set_policy(version=1, text="v1", requester="cli")
    clients = pg_store.list_clients()
    assert not clients
    # Seed one client through the real pairing path
    pairing = DojoPairing(pairing=pg_store, audit=pg_store, clock=FakeClock())
    rt = pairing.create_pairing_code(requester="cli").raw_code
    pairing.validate_code(code=rt, kind="device", name="Phone")
    client = pg_store.find_client_by_id(1)
    assert client is not None

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait(timeout=10)
        try:
            setup.accept_current_policy(client=client)
            results.append(True)
        except NoConsentPolicy:
            results.append(False)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True, True]
    assert pg_store.find_acceptance(1) is not None
    accepted = [e for e in pg_store.list_recent() if e.action == "consent.accepted"]
    assert len(accepted) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_setup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dojo.setup'`.

- [ ] **Step 3: Add `checklist_item` helper to `DojoSetup` (model helper on facade)**

Add to the facade a convenience accessor used by tests:
```python
    def checklist_item(self, key: str) -> SetupItem:
        return next(item for item in self.checklist() if item.key == key)
```

- [ ] **Step 4: Write the facade**

Create `dojo-core/src/dojo/setup.py`:
```python
from __future__ import annotations

from dojo.adapters.clock import SystemClock
from dojo.exceptions import ConsentPolicyDowngrade, NoConsentPolicy
from dojo.model import (
    AuditEvent,
    Client,
    ConsentAcceptance,
    ConsentPolicy,
    SetupItem,
)
from dojo.ports import AuditStore, Clock, PairingStore, SetupStore

PAIRING_ITEM = "pairing"
CONSENT_ITEM = "consent"


class DojoSetup:
    """Deep behavioral seam for first-run onboarding and media-consent policy.

    Owns the installation-wide consent-policy lifecycle, once-per-version
    acceptance recording (inherited by every client), the derived onboarding
    checklist, and the ``is_ready`` scheduling gate. FastAPI routes and the
    worker scheduler share this facade.
    """

    def __init__(
        self,
        *,
        setup: SetupStore,
        audit: AuditStore,
        pairing: PairingStore,
        clock: Clock | None = None,
    ) -> None:
        self._setup = setup
        self._audit = audit
        self._pairing = pairing
        self._clock = clock or SystemClock()

    def current_policy(self) -> ConsentPolicy | None:
        """Return the current (highest-version) consent policy, if any."""
        return self._setup.get_current_policy()

    def set_policy(self, *, version: int, text: str, requester: str) -> ConsentPolicy:
        """Create or replace a policy version; reject downgrades; audit."""
        current = self._setup.get_current_policy()
        if current is not None and version < current.version:
            raise ConsentPolicyDowngrade(
                f"cannot set version {version}; current is {current.version}"
            )
        now = self._clock.now()
        policy = self._setup.create_policy(
            version=version, text=text, created_by=requester, created_at=now
        )
        self._audit.append(
            AuditEvent(
                action="consent.policy_updated",
                actor=requester,
                occurred_at=now,
                details={"version": version},
            )
        )
        return policy

    def current_acceptance(self) -> ConsentAcceptance | None:
        """Return the acceptance for the current policy version, if any."""
        policy = self._setup.get_current_policy()
        if policy is None:
            return None
        return self._setup.find_acceptance(policy.version)

    def accept_current_policy(self, *, client: Client) -> ConsentAcceptance:
        """Accept the current policy version, once per version, idempotently."""
        policy = self._setup.get_current_policy()
        if policy is None:
            raise NoConsentPolicy("no consent policy configured")
        existing = self._setup.find_acceptance(policy.version)
        if existing is not None:
            return existing
        now = self._clock.now()
        acceptance = ConsentAcceptance(
            policy_version=policy.version,
            accepted_at=now,
            accepting_client_id=client.id,
            accepting_client_name=client.name,
            accepting_client_kind=client.kind,
        )
        if self._setup.record_acceptance(acceptance):
            self._audit.append(
                AuditEvent(
                    action="consent.accepted",
                    actor=str(client.id),
                    occurred_at=now,
                    details={"version": policy.version},
                )
            )
            return acceptance
        raced = self._setup.find_acceptance(policy.version)
        if raced is None:
            raise NoConsentPolicy("consent acceptance lost")
        return raced

    def checklist(self) -> list[SetupItem]:
        """Derive the onboarding checklist from real state."""
        policy = self._setup.get_current_policy()
        consent_done = (
            policy is not None and self._setup.find_acceptance(policy.version) is not None
        )
        pairing_done = any(c.revoked_at is None for c in self._pairing.list_clients())
        return [
            SetupItem(key=PAIRING_ITEM, label="Pairing", complete=pairing_done),
            SetupItem(key=CONSENT_ITEM, label="Media consent", complete=consent_done),
        ]

    def checklist_item(self, key: str) -> SetupItem:
        return next(item for item in self.checklist() if item.key == key)

    def is_ready(self) -> bool:
        """True when every onboarding checklist item is complete."""
        return all(item.complete for item in self.checklist())
```

- [ ] **Step 5: Export from `dojo`**

In `dojo-core/src/dojo/__init__.py`:
- add `from dojo.setup import DojoSetup` after the pairing import,
- add `ConsentError, ConsentPolicyDowngrade, NoConsentPolicy` to the exceptions import block,
- add `ConsentAcceptance, ConsentPolicy, SetupItem` to the `from dojo.model import (...)` block,
- add `"ConsentAcceptance"`, `"ConsentError"`, `"ConsentPolicy"`, `"ConsentPolicyDowngrade"`, `"DojoSetup"`, `"NoConsentPolicy"`, `"SetupItem"` to `__all__`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_setup.py -v`
Expected: PASS. If a test in Step 1 still references `ConsentAcceptance` without importing it, add `from dojo.model import ConsentAcceptance` to the test file from within `from dojo.model import Client, SetupItem`.

- [ ] **Step 7: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings (remove any now-unused imports ruff flags).
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/setup.py dojo-core/src/dojo/__init__.py dojo-core/tests/test_setup.py
git commit -m "feat(dojo-core): setup facade with consent policy, acceptance, checklist (#5)"
```

---

### Task 3: Setup API routes and app wiring

**Files:**
- Create: `backend/src/backend/routes/setup.py`
- Modify: `backend/src/backend/deps.py`
- Modify: `backend/src/backend/main.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `DojoSetup` (Task 2), `get_current_client` (from #3), `DojoSetup.current_policy()`, `DojoSetup.current_acceptance()`, `DojoSetup.checklist()`, `DojoSetup.is_ready()`, `DojoSetup.accept_current_policy(client=...)`, exceptions `ConsentPolicyDowngrade`, `NoConsentPolicy`.
- Produces: `backend.routes.setup.router` with `GET /api/setup`, `GET /api/setup/consent`, `POST /api/setup/consent/accept`; `backend.deps.build_setup() -> DojoSetup`; `app.state.setup`; router included under `get_current_client`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api.py`:
- update `make_app` to wire `DojoSetup` and return it as a 4th element:
```python
def make_app(tmp_path: Path) -> tuple[TestClient, DojoPublishing, DojoPairing, DojoSetup]:
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
    setup = DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    client = TestClient(create_app(publishing, pairing, activity, setup, cookie_secure=False))
    return client, publishing, pairing, setup
```
- update every existing `client, _, pairing = make_app(tmp_path)` call site to `client, _, pairing, _ = make_app(tmp_path)` (grep for `make_app(` to find them; the `test_browser_validate_sets_secure_http_only_cookie` test builds its own app and is untouched),
- update the `dojo` import line: `from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup, InMemoryStore`,
- append contract tests:
```python
def test_setup_routes_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/setup").status_code == 401
    assert client.get("/api/setup/consent").status_code == 401
    assert client.post("/api/setup/consent/accept").status_code == 401


def test_setup_without_policy_shows_incomplete(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    body = client.get("/api/setup", headers=bearer(token)).json()
    assert body["ready"] is False
    keys = {item["key"]: item["complete"] for item in body["checklist"]}
    assert keys["pairing"] is True
    assert keys["consent"] is False


def test_consent_404_until_policy_configured(tmp_path: Path) -> None:
    client, _, pairing, _ = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.get("/api/setup/consent", headers=bearer(token)).status_code == 404
    assert client.post("/api/setup/consent/accept", headers=bearer(token)).status_code == 404


def test_device_accepts_consent_and_setup_becomes_ready(tmp_path: Path) -> None:
    client, _, pairing, setup = make_app(tmp_path)
    token = pair_device(client, pairing)
    me = client.get("/api/pairing/me", headers=bearer(token)).json()
    setup.set_policy(version=1, text="Riza metni", requester=str(me["id"]))

    consent = client.get("/api/setup/consent", headers=bearer(token)).json()
    assert consent["version"] == 1
    assert consent["accepted_at"] is None

    accepted = client.post("/api/setup/consent/accept", headers=bearer(token))
    assert accepted.status_code == 200
    assert accepted.json()["version"] == 1

    again = client.post("/api/setup/consent/accept", headers=bearer(token))
    assert again.status_code == 200
    assert again.json()["accepted_at"] == accepted.json()["accepted_at"]

    consent = client.get("/api/setup/consent", headers=bearer(token)).json()
    assert consent["accepted_at"] == accepted.json()["accepted_at"]

    body = client.get("/api/setup", headers=bearer(token)).json()
    keys = {item["key"]: item["complete"] for item in body["checklist"]}
    assert keys["consent"] is True
    assert body["ready"] is True


def test_browser_session_accepts_consent(tmp_path: Path) -> None:
    client, _, pairing, setup = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    client.post("/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"})
    setup.set_policy(version=1, text="Riza metni", requester="cli")
    resp = client.post("/api/setup/consent/accept")
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.routes.setup'` and `create_app` rejects the extra positional arg.

- [ ] **Step 3: Add the dependency builder**

In `backend/src/backend/deps.py`, add `DojoSetup` to the `dojo` import and append:
```python
def build_setup() -> DojoSetup:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoSetup(setup=store, audit=store, pairing=store)
```

- [ ] **Step 4: Add the router**

Create `backend/src/backend/routes/setup.py`:
```python
from __future__ import annotations

from datetime import datetime

from dojo import Client, DojoSetup, NoConsentPolicy
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_setup(request: Request) -> DojoSetup:
    return request.app.state.setup


class SetupItemOut(BaseModel):
    key: str
    label: str
    complete: bool


class SetupOut(BaseModel):
    checklist: list[SetupItemOut]
    ready: bool


class ConsentOut(BaseModel):
    version: int
    text: str
    accepted_at: datetime | None


class AcceptanceOut(BaseModel):
    version: int
    accepted_at: datetime


router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("", response_model=SetupOut)
def setup_state(
    _client: Client = Depends(get_current_client),
    setup: DojoSetup = Depends(get_setup),
) -> SetupOut:
    return SetupOut(
        checklist=[SetupItemOut(**vars(item)) for item in setup.checklist()],
        ready=setup.is_ready(),
    )


@router.get("/consent", response_model=ConsentOut)
def get_consent(
    _client: Client = Depends(get_current_client),
    setup: DojoSetup = Depends(get_setup),
) -> ConsentOut:
    policy = setup.current_policy()
    if policy is None:
        raise HTTPException(status_code=404, detail="no consent policy configured")
    acceptance = setup.current_acceptance()
    return ConsentOut(
        version=policy.version,
        text=policy.text,
        accepted_at=acceptance.accepted_at if acceptance is not None else None,
    )


@router.post("/consent/accept", response_model=AcceptanceOut)
def accept_consent(
    client: Client = Depends(get_current_client),
    setup: DojoSetup = Depends(get_setup),
) -> AcceptanceOut:
    try:
        acceptance = setup.accept_current_policy(client=client)
    except NoConsentPolicy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AcceptanceOut(version=acceptance.policy_version, accepted_at=acceptance.accepted_at)
```

- [ ] **Step 5: Wire into the app**

In `backend/src/backend/main.py`:
- imports: `from dojo import DojoActivity, DojoPairing, DojoPublishing, DojoSetup`, `from backend.deps import build_activity, build_pairing, build_publishing, build_setup, get_current_client`, `from backend.routes import activity as activity_router`, `from backend.routes import setup as setup_router`,
- `lifespan`: after the activity block add:
```python
    if not hasattr(app.state, "setup"):
        app.state.setup = build_setup()
```
- `create_app` signature: `def create_app(publishing=None, pairing=None, activity=None, setup=None, cookie_secure=None)`; after the `activity` block add:
```python
    if setup is not None:
        app.state.setup = setup
```
- include the router after the activity include:
```python
    app.include_router(setup_router.router, dependencies=[Depends(get_current_client)])
```

- [ ] **Step 6: Run backend tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py backend/tests/test_cli.py -v`
Expected: PASS (walk the whole file; every `make_app` call site updated).

- [ ] **Step 7: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/setup.py backend/src/backend/deps.py backend/src/backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): setup and consent API with onboarding checklist (#5)"
```

---

### Task 4: `dojo-consent set-policy` CLI

**Files:**
- Modify: `backend/src/backend/cli.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `DojoSetup.set_policy(version=, text=, requester="cli")`, `PostgresStore`.
- Produces: `backend.cli.set_consent_policy(setup, *, version, text) -> ConsentPolicy` and `backend.cli.consent_main(argv) -> int` wired as console script `dojo-consent`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_cli.py`:
```python
from dojo import DojoSetup, InMemoryStore

from backend.cli import consent_main, set_consent_policy


def test_set_consent_policy_audits_cli_actor() -> None:
    store = InMemoryStore()
    setup = DojoSetup(setup=store, audit=store, pairing=store, clock=FakeClock())
    policy = set_consent_policy(setup, version=1, text="Riza metni")
    assert policy.version == 1
    events = [e for e in store.list_recent() if e.action == "consent.policy_updated"]
    assert len(events) == 1
    assert events[0].actor == "cli"


def test_consent_main_requires_version_and_text() -> None:
    with pytest.raises(SystemExit) as exc:
        consent_main(["set-policy", "--version", "1"])
    assert exc.value.code == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_cli.py -v`
Expected: FAIL — `module 'backend.cli' has no attribute 'set_consent_policy'` / `consent_main`.

- [ ] **Step 3: Add the CLI functions**

In `backend/src/backend/cli.py`, extend the imports:
```python
from dojo import DojoPairing, DojoSetup
from dojo.model import ConsentPolicy
```
and append:
```python
def set_consent_policy(setup: DojoSetup, *, version: int, text: str) -> ConsentPolicy:
    return setup.set_policy(version=version, text=text, requester="cli")


def consent_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-consent")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_policy_parser = subparsers.add_parser("set-policy")
    set_policy_parser.add_argument("--version", type=int, required=True)
    set_policy_parser.add_argument("--text", required=True)
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    setup = DojoSetup(setup=store, audit=store, pairing=store)
    policy = set_consent_policy(setup, version=args.version, text=args.text)
    print(f"Consent policy v{policy.version} saved")
    return 0
```

- [ ] **Step 4: Wire the console script**

In `backend/pyproject.toml`, under `[project.scripts]`, add:
```toml
dojo-consent = "backend.cli:consent_main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_cli.py -v`
Expected: PASS (both new tests; `test_consent_main_requires_version_and_text` needs `import pytest` at the top of `backend/tests/test_cli.py` if not already imported).

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/cli.py backend/pyproject.toml backend/tests/test_cli.py
git commit -m "feat(backend): dojo-consent set-policy CLI (#5)"
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

Check the spec (`docs/superpowers/specs/2026-08-12-media-consent-and-first-run-onboarding-design.md`):
- consent prompt per policy version, acceptance once per version, inherited by new clients → `set_policy`/`accept_current_policy` + `GET /api/setup/consent` + idempotent `POST /api/setup/consent/accept` (Tasks 1-3 tests).
- first-run setup checklist tracks required configuration; scheduling gated → derived `checklist()` + `is_ready()` exposed in `GET /api/setup` (Task 2-3 tests).
- consent acceptance and onboarding state visible to clients → `GET /api/setup` and `GET /api/setup/consent` for both client kinds (Task 3 tests).

- [ ] **Step 4: Commit any stragglers and note the follow-up**

No new files expected beyond Tasks 1-4. If a stray file exists, commit it. Do not close issue #5 — implementation completion is reported by the implementer, and closing is handled separately after /code-review.