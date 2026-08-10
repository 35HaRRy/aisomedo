# Pairing and Equal-Privilege Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add accountless pairing and equal-privilege authorization: a short-lived single-use one-time code pairs an Android device (opaque bearer token) or a browser (HttpOnly cookie session); paired clients can be listed and revoked, and revoked/stale credentials are denied, with pairing/revocation audited against the acting client.

**Architecture:** A new `DojoPairing` deep facade in `dojo-core` (alongside `DojoPublishing`) owns pairing flows and credential verification against a `PairingStore` port (implemented by `PostgresStore` and `InMemoryStore`), a SHA-256 `Hasher`, a `SecretGenerator`, the `Clock`, and the shared `AuditStore`. FastAPI wires both facades; a `get_current_client` dependency guards all business routes (bearer token or `dojo_session` cookie). Bootstrap is an admin CLI command. All secrets (codes, tokens, session ids) are stored only as SHA-256 hashes.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, SQLAlchemy 2.0, alembic, psycopg3, pytest, testcontainers-python, ruff, mypy.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md`: `Dojo Paylaşım Paketi`, `Dojo Yayın Planı`, `Yayın Zamanı`, `Yayın İncelemesi`, `Tamamlanmış Paket`. Use these in docstrings; pairing client vocabulary (`client`, `device`, `browser`, `pairing code`) is new domain language.
- Never persist a raw code, bearer token, or session id — only SHA-256 hashes.
- Pairing codes: 8 chars from a 32-char alphabet (no `0/O/1/I/l`), 10-minute TTL, single-use (burned on success). No per-code wrong-try cap (hash lookup makes it a no-op).
- Browser sessions: HttpOnly+Secure+SameSite=Lax cookie, 30-day idle TTL. Device tokens: revoke-only, no TTL.
- Equal permissions: no roles. Any paired client can mint codes, list clients, and revoke any client.
- Audit: `pairing.code_created`, `pairing.client_paired`, `pairing.client_revoked` with actor = acting client id (bootstrap uses `"cli"`).
- Protected surface: all `/api` routes except `/health` and `POST /api/pairing/validate`. The validate endpoint is per-IP throttled (10 attempts/min, in-memory, per-process).
- Commands run from repo root unless a task says otherwise. All paths relative to repo root.
- Lint: ruff (`E,F,I,UP`). Typecheck: mypy `disallow_untyped_defs` (strict in backend). Both must pass before each task's commit.
- Every Python task: run the focused test file first, then the package's full suite, before committing.
- Tests run against real PostgreSQL via the `pg_store` fixture (testcontainers). Domain tests use `FakeClock`/`MutableClock`; the hasher is real SHA-256; the generator is real randomness (the facade returns raw codes/tokens, so tests never need to guess secrets).

---

### Task 1: Model dataclasses, exceptions, ports, secret adapters

**Files:**
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/exceptions.py`
- Modify: `dojo-core/src/dojo/ports.py`
- Create: `dojo-core/src/dojo/adapters/secrets.py`
- Modify: `dojo-core/src/dojo/adapters/__init__.py`
- Modify: `dojo-core/src/dojo/__init__.py`
- Test: `dojo-core/tests/test_secrets.py`

**Interfaces:**
- Consumes: nothing (existing `DojoError`, `AuditEvent`).
- Produces: `dojo.PairingCode(id:int, code_hash:str, expires_at:datetime, created_by:str, created_at:datetime, consumed_at:datetime|None=None)`; `dojo.PairingCodeIssued(raw_code:str, expires_at:datetime)`; `dojo.Client(id:int, name:str, kind:str, created_at:datetime, created_by:str, last_seen_at:datetime|None=None, revoked_at:datetime|None=None)`; `dojo.PairingResult(client_id:int, kind:str, raw_credential:str)`; exceptions `PairingError`, `PairingCodeInvalid`, `PairingCodeExpired`, `PairingCodeConsumed`, `ClientNotFound`; protocols `Hasher.hash(secret)->str`, `SecretGenerator.generate_code()->str`/`generate_token()->str`, `PairingStore` (full signature set in Task 2); `Sha256Hasher`, `RandomSecretGenerator`.

- [ ] **Step 1: Write the failing tests**

`dojo-core/tests/test_secrets.py`:
```python
from __future__ import annotations

from dojo.adapters.secrets import (
    CODE_ALPHABET,
    CODE_LENGTH,
    RandomSecretGenerator,
    Sha256Hasher,
)


def test_sha256_hashes_deterministically() -> None:
    hasher = Sha256Hasher()
    assert hasher.hash("abc") == hasher.hash("abc")
    assert hasher.hash("abc") != hasher.hash("abd")
    assert len(hasher.hash("abc")) == 64


def test_generate_code_shape() -> None:
    generator = RandomSecretGenerator()
    code = generator.generate_code()
    assert len(code) == CODE_LENGTH
    assert all(c in CODE_ALPHABET for c in code)
    assert code != generator.generate_code()


def test_generate_token_is_urlsafe_and_long() -> None:
    token = RandomSecretGenerator().generate_token()
    assert len(token) >= 32
    assert token.replace("-", "").replace("_", "").isalnum()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_secrets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dojo.adapters.secrets'`

- [ ] **Step 3: Add model dataclasses**

Append to `dojo-core/src/dojo/model.py`:
```python
@dataclass(frozen=True)
class PairingCode:
    id: int
    code_hash: str
    expires_at: datetime
    created_by: str
    created_at: datetime
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class PairingCodeIssued:
    raw_code: str
    expires_at: datetime


@dataclass(frozen=True)
class Client:
    id: int
    name: str
    kind: str
    created_at: datetime
    created_by: str
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class PairingResult:
    client_id: int
    kind: str
    raw_credential: str
```

- [ ] **Step 4: Add exceptions**

Append to `dojo-core/src/dojo/exceptions.py`:
```python
class PairingError(DojoError):
    pass


class PairingCodeInvalid(PairingError):
    pass


class PairingCodeExpired(PairingError):
    pass


class PairingCodeConsumed(PairingError):
    pass


class ClientNotFound(PairingError):
    pass
```

- [ ] **Step 5: Add ports**

Append to `dojo-core/src/dojo/ports.py` (imports: `from dojo.model import AuditEvent, Client, Package, PairingCode`):
```python
@runtime_checkable
class Hasher(Protocol):
    def hash(self, secret: str) -> str: ...


@runtime_checkable
class SecretGenerator(Protocol):
    def generate_code(self) -> str: ...
    def generate_token(self) -> str: ...


@runtime_checkable
class PairingStore(Protocol):
    def create_code(self, code: PairingCode) -> PairingCode: ...
    def find_code_by_hash(self, code_hash: str) -> PairingCode | None: ...
    def mark_code_consumed(self, code_id: int, at: datetime) -> bool: ...
    def find_client_by_id(self, client_id: int) -> Client | None: ...
    def create_client(self, client: Client, credential_hash: str) -> Client: ...
    def find_client_by_credential_hash(self, credential_hash: str) -> Client | None: ...
    def list_clients(self) -> list[Client]: ...
    def mark_client_revoked(self, client_id: int, at: datetime) -> None: ...
    def touch_client(self, client_id: int, at: datetime) -> None: ...
```

- [ ] **Step 6: Add secret adapters**

`dojo-core/src/dojo/adapters/secrets.py`:
```python
from __future__ import annotations

import base64
import hashlib
import secrets as stdlib_secrets

CODE_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"
CODE_LENGTH = 8
TOKEN_BYTES = 32


class Sha256Hasher:
    def hash(self, secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class RandomSecretGenerator:
    def generate_code(self) -> str:
        return "".join(stdlib_secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))

    def generate_token(self) -> str:
        return base64.urlsafe_b64encode(stdlib_secrets.token_bytes(TOKEN_BYTES)).decode("ascii")
```

Update `dojo-core/src/dojo/adapters/__init__.py`:
```python
from dojo.adapters.clock import SystemClock
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.secrets import RandomSecretGenerator, Sha256Hasher
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore

__all__ = [
    "InMemoryStore",
    "RandomSecretGenerator",
    "Sha256Hasher",
    "StubMetaPublisher",
    "StubNotifier",
    "StubSignedUrlStore",
    "SystemClock",
]
```

Update `dojo-core/src/dojo/__init__.py` to import and re-export the new model types, exceptions, and adapters:
```python
from dojo.adapters import (
    InMemoryStore,
    RandomSecretGenerator,
    Sha256Hasher,
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
    SystemClock,
)
from dojo.exceptions import (
    ActivePackageExists,
    ClientNotFound,
    DojoError,
    NoActivePackage,
    PairingCodeConsumed,
    PairingCodeExpired,
    PairingCodeInvalid,
    PairingError,
)
from dojo.model import (
    PACKAGE_FOLDER_FORMAT,
    AuditEvent,
    Client,
    Manifest,
    Package,
    PairingCode,
    PairingCodeIssued,
    PairingResult,
)
from dojo.publishing import DojoPublishing

__all__ = [
    "ActivePackageExists",
    "AuditEvent",
    "Client",
    "ClientNotFound",
    "DojoError",
    "DojoPublishing",
    "InMemoryStore",
    "Manifest",
    "NoActivePackage",
    "PACKAGE_FOLDER_FORMAT",
    "Package",
    "PairingCode",
    "PairingCodeConsumed",
    "PairingCodeExpired",
    "PairingCodeInvalid",
    "PairingCodeIssued",
    "PairingError",
    "PairingResult",
    "RandomSecretGenerator",
    "Sha256Hasher",
    "StubMetaPublisher",
    "StubNotifier",
    "StubSignedUrlStore",
    "SystemClock",
]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_secrets.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/model.py dojo-core/src/dojo/exceptions.py dojo-core/src/dojo/ports.py dojo-core/src/dojo/adapters/secrets.py dojo-core/src/dojo/adapters/__init__.py dojo-core/src/dojo/__init__.py dojo-core/tests/test_secrets.py
git commit -m "feat(dojo-core): pairing model, exceptions, ports, secret adapters (#3)"
```

---

### Task 2: Pairing store layer — SQLAlchemy rows, PostgresStore + InMemoryStore methods, migration, harness

**Files:**
- Modify: `dojo-core/src/dojo/adapters/db.py`
- Modify: `dojo-core/src/dojo/adapters/memory.py`
- Create: `dojo-core/migrations/versions/0002_pairing.py`
- Modify: `dojo-core/tests/conftest.py`
- Test: `dojo-core/tests/test_store_pairing.py`

**Interfaces:**
- Consumes: `PairingCode`, `Client` dataclasses and `PairingStore` protocol from Task 1.
- Produces: `PostgresStore` and `InMemoryStore` implementing every `PairingStore` method; tables `pairing_codes` and `clients` in `Base.metadata` and in alembic `0002_pairing`; `pg_store` fixture truncates all four tables.

- [ ] **Step 1: Write the failing tests**

`dojo-core/tests/test_store_pairing.py`:
```python
from __future__ import annotations

from dojo.adapters.db import PostgresStore
from dojo.model import Client, PairingCode
from dojo.testing import FIXED_AT


def test_code_roundtrip(pg_store: PostgresStore) -> None:
    code = pg_store.create_code(
        PairingCode(
            id=0,
            code_hash="abc123",
            expires_at=FIXED_AT,
            created_by="cli",
            created_at=FIXED_AT,
        )
    )
    assert code.id > 0
    found = pg_store.find_code_by_hash("abc123")
    assert found is not None
    assert found.created_by == "cli"
    assert pg_store.find_code_by_hash("nope") is None


def test_mark_consumed_single_use(pg_store: PostgresStore) -> None:
    code = pg_store.create_code(
        PairingCode(id=0, code_hash="h1", expires_at=FIXED_AT, created_by="cli", created_at=FIXED_AT)
    )
    assert pg_store.mark_code_consumed(code.id, FIXED_AT) is True
    assert pg_store.mark_code_consumed(code.id, FIXED_AT) is False
    found = pg_store.find_code_by_hash("h1")
    assert found is not None
    assert found.consumed_at is not None


def test_client_roundtrip_and_lookup(pg_store: PostgresStore) -> None:
    client = pg_store.create_client(
        Client(id=0, name="Phone", kind="device", created_at=FIXED_AT, created_by="cli"),
        credential_hash="credhash1",
    )
    assert client.id > 0
    by_hash = pg_store.find_client_by_credential_hash("credhash1")
    assert by_hash is not None
    assert by_hash.name == "Phone"
    by_id = pg_store.find_client_by_id(client.id)
    assert by_id is not None
    assert pg_store.find_client_by_credential_hash("nope") is None


def test_list_revoke_touch(pg_store: PostgresStore) -> None:
    first = pg_store.create_client(
        Client(id=0, name="Phone", kind="device", created_at=FIXED_AT, created_by="cli"),
        credential_hash="h1",
    )
    pg_store.create_client(
        Client(id=0, name="Browser", kind="browser", created_at=FIXED_AT, created_by="cli"),
        credential_hash="h2",
    )
    assert len(pg_store.list_clients()) == 2

    pg_store.mark_client_revoked(first.id, FIXED_AT)
    revoked = pg_store.find_client_by_id(first.id)
    assert revoked is not None
    assert revoked.revoked_at is not None

    pg_store.touch_client(first.id, FIXED_AT)
    touched = pg_store.find_client_by_id(first.id)
    assert touched is not None
    assert touched.last_seen_at == FIXED_AT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_pairing.py -v`
Expected: FAIL — `AttributeError` (missing methods) on `PostgresStore`/`InMemoryStore`.

- [ ] **Step 3: Add SQLAlchemy rows**

In `dojo-core/src/dojo/adapters/db.py`, after `AuditRow`:
```python
class PairingCodeRow(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientRow(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Add PostgresStore methods**

In `dojo-core/src/dojo/adapters/db.py`, update the import to `from sqlalchemy import JSON, DateTime, String, create_engine, select, update`, import `Client, PairingCode` from `dojo.model`, and append to `PostgresStore`:
```python
    def create_code(self, code: PairingCode) -> PairingCode:
        with self._session() as session:
            row = PairingCodeRow(
                code_hash=code.code_hash,
                expires_at=code.expires_at,
                created_by=code.created_by,
                created_at=code.created_at,
                consumed_at=code.consumed_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return PairingCode(
                id=row.id,
                code_hash=row.code_hash,
                expires_at=row.expires_at,
                created_by=row.created_by,
                created_at=row.created_at,
                consumed_at=row.consumed_at,
            )

    def find_code_by_hash(self, code_hash: str) -> PairingCode | None:
        with self._session() as session:
            row = session.scalar(select(PairingCodeRow).where(PairingCodeRow.code_hash == code_hash))
            if row is None:
                return None
            return PairingCode(
                id=row.id,
                code_hash=row.code_hash,
                expires_at=row.expires_at,
                created_by=row.created_by,
                created_at=row.created_at,
                consumed_at=row.consumed_at,
            )

    def mark_code_consumed(self, code_id: int, at: datetime) -> bool:
        with self._session() as session:
            result = session.execute(
                update(PairingCodeRow)
                .where(PairingCodeRow.id == code_id, PairingCodeRow.consumed_at.is_(None))
                .values(consumed_at=at)
            )
            session.commit()
            return result.rowcount > 0

    def create_client(self, client: Client, credential_hash: str) -> Client:
        with self._session() as session:
            row = ClientRow(
                name=client.name,
                kind=client.kind,
                created_at=client.created_at,
                created_by=client.created_by,
                credential_hash=credential_hash,
                last_seen_at=client.last_seen_at,
                revoked_at=client.revoked_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._client_from_row(row)

    def find_client_by_id(self, client_id: int) -> Client | None:
        with self._session() as session:
            row = session.get(ClientRow, client_id)
            return self._client_from_row(row) if row is not None else None

    def find_client_by_credential_hash(self, credential_hash: str) -> Client | None:
        with self._session() as session:
            row = session.scalar(
                select(ClientRow).where(ClientRow.credential_hash == credential_hash)
            )
            return self._client_from_row(row) if row is not None else None

    def list_clients(self) -> list[Client]:
        with self._session() as session:
            rows = session.scalars(select(ClientRow).order_by(ClientRow.id)).all()
            return [self._client_from_row(row) for row in rows]

    def mark_client_revoked(self, client_id: int, at: datetime) -> None:
        with self._session() as session:
            session.execute(
                update(ClientRow)
                .where(ClientRow.id == client_id, ClientRow.revoked_at.is_(None))
                .values(revoked_at=at)
            )
            session.commit()

    def touch_client(self, client_id: int, at: datetime) -> None:
        with self._session() as session:
            session.execute(update(ClientRow).where(ClientRow.id == client_id).values(last_seen_at=at))
            session.commit()

    @staticmethod
    def _client_from_row(row: ClientRow) -> Client:
        return Client(
            id=row.id,
            name=row.name,
            kind=row.kind,
            created_at=row.created_at,
            created_by=row.created_by,
            last_seen_at=row.last_seen_at,
            revoked_at=row.revoked_at,
        )
```

- [ ] **Step 5: Add InMemoryStore methods**

In `dojo-core/src/dojo/adapters/memory.py`, update the import to `from dojo.model import AuditEvent, Client, Package, PairingCode`, add `self._codes: list[PairingCode] = []`, `self._clients: list[Client] = []`, `self._client_hashes: dict[int, str] = {}`, `self._next_code_id = 1`, `self._next_client_id = 1` to `__init__`, and append:
```python
    def create_code(self, code: PairingCode) -> PairingCode:
        created = replace(code, id=self._next_code_id)
        self._next_code_id += 1
        self._codes.append(created)
        return created

    def find_code_by_hash(self, code_hash: str) -> PairingCode | None:
        return next((c for c in self._codes if c.code_hash == code_hash), None)

    def mark_code_consumed(self, code_id: int, at: datetime) -> bool:
        for i, code in enumerate(self._codes):
            if code.id == code_id and code.consumed_at is None:
                self._codes[i] = replace(code, consumed_at=at)
                return True
        return False

    def find_client_by_id(self, client_id: int) -> Client | None:
        return next((c for c in self._clients if c.id == client_id), None)

    def create_client(self, client: Client, credential_hash: str) -> Client:
        created = replace(client, id=self._next_client_id)
        self._next_client_id += 1
        self._client_hashes[created.id] = credential_hash
        self._clients.append(created)
        return created

    def find_client_by_credential_hash(self, credential_hash: str) -> Client | None:
        for client in self._clients:
            if self._client_hashes.get(client.id) == credential_hash:
                return client
        return None

    def list_clients(self) -> list[Client]:
        return list(self._clients)

    def mark_client_revoked(self, client_id: int, at: datetime) -> None:
        for i, client in enumerate(self._clients):
            if client.id == client_id and client.revoked_at is None:
                self._clients[i] = replace(client, revoked_at=at)
                return

    def touch_client(self, client_id: int, at: datetime) -> None:
        for i, client in enumerate(self._clients):
            if client.id == client_id:
                self._clients[i] = replace(client, last_seen_at=at)
                return
```
Add `from datetime import datetime` to the imports in `memory.py`.

- [ ] **Step 6: Write the alembic migration**

`dojo-core/migrations/versions/0002_pairing.py`:
```python
"""pairing_codes and clients

Revision ID: 0002_pairing
Revises: 0001_initial
Create Date: 2026-08-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_pairing"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_pairing_codes_code_hash", "pairing_codes", ["code_hash"])
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("credential_hash", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("credential_hash"),
    )
    op.create_index("ix_clients_credential_hash", "clients", ["credential_hash"])


def downgrade() -> None:
    op.drop_index("ix_clients_credential_hash", table_name="clients")
    op.drop_table("clients")
    op.drop_index("ix_pairing_codes_code_hash", table_name="pairing_codes")
    op.drop_table("pairing_codes")
```

- [ ] **Step 7: Extend the harness truncation**

In `dojo-core/tests/conftest.py`, replace the truncation block in `pg_store` with:
```python
    with store._session() as session:  # noqa: SLF001
        for table in ("pairing_codes", "clients", "audit_events", "packages"):
            session.execute(Base.metadata.tables[table].delete())
        session.commit()
    yield store
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_store_pairing.py -v`
Expected: PASS (4 passed)

- [ ] **Step 9: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/adapters/db.py dojo-core/src/dojo/adapters/memory.py dojo-core/migrations/versions/0002_pairing.py dojo-core/tests/conftest.py dojo-core/tests/test_store_pairing.py
git commit -m "feat(dojo-core): pairing store tables and adapters (#3)"
```

---

### Task 3: DojoPairing facade — code creation and validation (pairing flows)

**Files:**
- Create: `dojo-core/src/dojo/pairing.py`
- Modify: `dojo-core/src/dojo/__init__.py`
- Test: `dojo-core/tests/test_pairing.py`

**Interfaces:**
- Consumes: `PairingStore`/`Hasher`/`SecretGenerator`/`Clock`/`AuditStore` (Tasks 1-2), `SystemClock`, `Sha256Hasher`, `RandomSecretGenerator`, `PairingCode`, `PairingCodeIssued`, `PairingResult`, `AuditEvent`, exceptions.
- Produces: `DojoPairing(*, pairing: PairingStore, audit: AuditStore, clock=None, hasher=None, generator=None)` with `create_pairing_code(*, requester: str) -> PairingCodeIssued` and `validate_code(*, code: str, kind: str, name: str) -> PairingResult`. Constants `CODE_TTL = timedelta(minutes=10)`, `IDLE_TTL = timedelta(days=30)`.

- [ ] **Step 1: Write the failing tests**

`dojo-core/tests/test_pairing.py`:
```python
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from dojo import (
    ClientNotFound,
    DojoPairing,
    PairingCodeConsumed,
    PairingCodeExpired,
    PairingCodeInvalid,
)
from dojo.adapters.memory import InMemoryStore
from dojo.adapters.secrets import Sha256Hasher
from dojo.model import AuditEvent, PairingCodeIssued, PairingResult
from dojo.pairing import CODE_TTL, IDLE_TTL
from dojo.testing import FIXED_AT


class MutableClock:
    def __init__(self, now: datetime = FIXED_AT) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def make_pairing() -> tuple[DojoPairing, InMemoryStore, MutableClock]:
    store = InMemoryStore()
    clock = MutableClock()
    pairing = DojoPairing(pairing=store, audit=store, clock=clock)
    return pairing, store, clock


def test_create_code_returns_raw_and_expiry() -> None:
    pairing, store, _ = make_pairing()
    issued = pairing.create_pairing_code(requester="cli")
    assert isinstance(issued, PairingCodeIssued)
    assert len(issued.raw_code) == 8
    assert issued.expires_at - FIXED_AT == CODE_TTL
    events = [e for e in store.list_recent() if e.action == "pairing.code_created"]
    assert len(events) == 1
    assert events[0].actor == "cli"


def test_pair_device_issues_authenticatable_token() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    assert isinstance(result, PairingResult)
    assert result.kind == "device"
    client = pairing.authenticate_bearer(result.raw_credential)
    assert client is not None
    assert client.name == "Phone"


def test_pair_browser_issues_session() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    client = pairing.authenticate_session(result.raw_credential)
    assert client is not None
    assert client.kind == "browser"


def test_code_is_single_use() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    pairing.validate_code(code=code, kind="device", name="Phone")
    with pytest.raises(PairingCodeConsumed):
        pairing.validate_code(code=code, kind="device", name="Other")


def test_code_expires() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    clock.advance(timedelta(minutes=11))
    with pytest.raises(PairingCodeExpired):
        pairing.validate_code(code=code, kind="device", name="Phone")


def test_unknown_code_rejected() -> None:
    pairing, _, _ = make_pairing()
    with pytest.raises(PairingCodeInvalid):
        pairing.validate_code(code="aaaaaaaa", kind="device", name="Phone")


def test_bad_kind_rejected_without_consuming() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    with pytest.raises(ValueError):
        pairing.validate_code(code=code, kind="laptop", name="Laptop")
    pairing.validate_code(code=code, kind="device", name="Phone")  # still usable


def test_pairing_audited_with_acting_client() -> None:
    pairing, store, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    pairing.validate_code(code=code, kind="device", name="Phone")
    paired: list[AuditEvent] = [e for e in store.list_recent() if e.action == "pairing.client_paired"]
    assert len(paired) == 1
    assert paired[0].actor == "cli"
    assert paired[0].details["name"] == "Phone"
    assert paired[0].details["kind"] == "device"


def test_hashes_never_match_secrets() -> None:
    pairing, store, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    stored_codes = [c.code_hash for c in store._codes]  # noqa: SLF001
    stored_clients = list(store._client_hashes.values())  # noqa: SLF001
    assert code not in stored_codes
    assert result.raw_credential not in stored_clients
    assert Sha256Hasher().hash(code) in stored_codes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_pairing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dojo.pairing'` (or `DojoPairing` not importable).

- [ ] **Step 3: Write the facade**

`dojo-core/src/dojo/pairing.py`:
```python
from __future__ import annotations

from datetime import datetime, timedelta

from dojo.adapters.clock import SystemClock
from dojo.adapters.secrets import RandomSecretGenerator, Sha256Hasher
from dojo.exceptions import (
    PairingCodeConsumed,
    PairingCodeExpired,
    PairingCodeInvalid,
)
from dojo.model import AuditEvent, Client, PairingCode, PairingCodeIssued, PairingResult
from dojo.ports import AuditStore, Clock, Hasher, PairingStore, SecretGenerator

CODE_TTL = timedelta(minutes=10)
IDLE_TTL = timedelta(days=30)
SUPPORTED_KINDS = ("device", "browser")


class DojoPairing:
    """Deep behavioral seam for accountless pairing and equal-privilege auth.

    Owns pairing-code issuance, single-use validation, client listing and
    revocation, and credential verification. FastAPI guards routes through
    this facade; only the wall clock, hashing, and secret generation are
    swappable adapters.
    """

    def __init__(
        self,
        *,
        pairing: PairingStore,
        audit: AuditStore,
        clock: Clock | None = None,
        hasher: Hasher | None = None,
        generator: SecretGenerator | None = None,
    ) -> None:
        self._pairing = pairing
        self._audit = audit
        self._clock = clock or SystemClock()
        self._hasher = hasher or Sha256Hasher()
        self._generator = generator or RandomSecretGenerator()

    def create_pairing_code(self, *, requester: str) -> PairingCodeIssued:
        raw = self._generator.generate_code()
        now = self._clock.now()
        code = self._pairing.create_code(
            PairingCode(
                id=0,
                code_hash=self._hasher.hash(raw),
                expires_at=now + CODE_TTL,
                created_by=requester,
                created_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="pairing.code_created",
                actor=requester,
                occurred_at=now,
                details={"code_id": code.id, "ttl_seconds": int(CODE_TTL.total_seconds())},
            )
        )
        return PairingCodeIssued(raw_code=raw, expires_at=code.expires_at)

    def validate_code(self, *, code: str, kind: str, name: str) -> PairingResult:
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"unsupported client kind: {kind}")
        now = self._clock.now()
        found = self._pairing.find_code_by_hash(self._hasher.hash(code))
        if found is None:
            raise PairingCodeInvalid("invalid pairing code")
        if found.consumed_at is not None:
            raise PairingCodeConsumed("pairing code already used")
        if now > found.expires_at:
            raise PairingCodeExpired("pairing code expired")
        if not self._pairing.mark_code_consumed(found.id, now):
            raise PairingCodeConsumed("pairing code already used")

        raw_credential = self._generator.generate_token()
        client = self._pairing.create_client(
            Client(
                id=0,
                name=name,
                kind=kind,
                created_at=now,
                created_by=found.created_by,
                last_seen_at=now,
            ),
            credential_hash=self._hasher.hash(raw_credential),
        )
        self._audit.append(
            AuditEvent(
                action="pairing.client_paired",
                actor=found.created_by,
                occurred_at=now,
                details={"client_id": client.id, "name": name, "kind": kind},
            )
        )
        return PairingResult(client_id=client.id, kind=kind, raw_credential=raw_credential)
```

Update `dojo-core/src/dojo/__init__.py` to import `DojoPairing` from `dojo.pairing` and add it to `__all__` (alongside `DojoPublishing`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_pairing.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/pairing.py dojo-core/src/dojo/__init__.py dojo-core/tests/test_pairing.py
git commit -m "feat(dojo-core): pairing facade with code issuance and single-use validation (#3)"
```

---

### Task 4: DojoPairing facade — listing, revocation, credential verification

**Files:**
- Modify: `dojo-core/src/dojo/pairing.py`
- Test: `dojo-core/tests/test_pairing.py`

**Interfaces:**
- Consumes: `DojoPairing` from Task 3, `ClientNotFound` exception.
- Produces: `DojoPairing.list_clients() -> list[Client]`; `DojoPairing.revoke_client(*, client_id: int, requester: str) -> None`; `DojoPairing.authenticate_bearer(token: str) -> Client | None`; `DojoPairing.authenticate_session(session_id: str) -> Client | None`. `IDLE_TTL` used only for browser clients.

- [ ] **Step 1: Write the failing tests**

Append to `dojo-core/tests/test_pairing.py`:
```python
def test_revoke_denies_device() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    assert pairing.authenticate_bearer(result.raw_credential) is not None
    pairing.revoke_client(client_id=result.client_id, requester="cli")
    assert pairing.authenticate_bearer(result.raw_credential) is None


def test_revoke_denies_browser_session() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    assert pairing.authenticate_session(result.raw_credential) is not None
    pairing.revoke_client(client_id=result.client_id, requester="cli")
    assert pairing.authenticate_session(result.raw_credential) is None


def test_revoke_unknown_client_raises() -> None:
    pairing, _, _ = make_pairing()
    with pytest.raises(ClientNotFound):
        pairing.revoke_client(client_id=999, requester="cli")


def test_revoke_is_idempotent() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester="cli")
    pairing.revoke_client(client_id=result.client_id, requester="cli")


def test_revocation_audited_with_acting_client() -> None:
    pairing, store, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    pairing.revoke_client(client_id=result.client_id, requester="2")
    revoked = [e for e in store.list_recent() if e.action == "pairing.client_revoked"]
    assert len(revoked) == 1
    assert revoked[0].actor == "2"
    assert revoked[0].details["client_id"] == result.client_id


def test_browser_session_idle_expiry() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    clock.advance(IDLE_TTL)
    assert pairing.authenticate_session(result.raw_credential) is not None
    clock.advance(timedelta(days=1))
    assert pairing.authenticate_session(result.raw_credential) is None


def test_activity_resets_idle_ttl() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="browser", name="Browser")
    clock.advance(IDLE_TTL - timedelta(days=1))
    assert pairing.authenticate_session(result.raw_credential) is not None
    clock.advance(IDLE_TTL - timedelta(days=1))
    assert pairing.authenticate_session(result.raw_credential) is not None


def test_device_token_never_idle_expires() -> None:
    pairing, _, clock = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    result = pairing.validate_code(code=code, kind="device", name="Phone")
    clock.advance(timedelta(days=400))
    assert pairing.authenticate_bearer(result.raw_credential) is not None


def test_list_clients_shows_revoked_flag() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    a = pairing.validate_code(code=code, kind="device", name="Phone")
    code = pairing.create_pairing_code(requester=str(a.client_id)).raw_code
    b = pairing.validate_code(code=code, kind="browser", name="Browser")
    pairing.revoke_client(client_id=a.client_id, requester=str(b.client_id))
    clients = {c.id: c for c in pairing.list_clients()}
    assert clients[a.client_id].revoked_at is not None
    assert clients[b.client_id].revoked_at is None


def test_equal_permissions_any_client_can_mint_and_revoke() -> None:
    pairing, _, _ = make_pairing()
    code = pairing.create_pairing_code(requester="cli").raw_code
    a = pairing.validate_code(code=code, kind="device", name="A")
    code = pairing.create_pairing_code(requester=str(a.client_id)).raw_code
    b = pairing.validate_code(code=code, kind="device", name="B")
    pairing.revoke_client(client_id=b.client_id, requester=str(a.client_id))
    assert pairing.authenticate_bearer(b.raw_credential) is None


def test_single_use_under_concurrency(pg_store) -> None:
    import threading

    pairing = DojoPairing(pairing=pg_store, audit=pg_store)
    code = pairing.create_pairing_code(requester="cli").raw_code
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        try:
            barrier.wait(timeout=10)
            pairing.validate_code(code=code, kind="device", name="race")
            results.append("ok")
        except PairingCodeConsumed:
            results.append("consumed")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["consumed", "ok"]
```
(Note: `test_single_use_under_concurrency(pg_store)` requires the real-Postgres fixture, so the file's imports must include the DB adapter test conftest fixture; this test requests `pg_store` and needs no in-memory store.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_pairing.py -v`
Expected: FAIL — `AttributeError` on the new facade methods.

- [ ] **Step 3: Add facade methods**

In `dojo-core/src/dojo/pairing.py`, add `from dojo.exceptions import ClientNotFound` and append to `DojoPairing`:
```python
    def list_clients(self) -> list[Client]:
        return self._pairing.list_clients()

    def revoke_client(self, *, client_id: int, requester: str) -> None:
        client = self._pairing.find_client_by_id(client_id)
        if client is None:
            raise ClientNotFound(f"no client {client_id}")
        if client.revoked_at is not None:
            return
        now = self._clock.now()
        self._pairing.mark_client_revoked(client_id, now)
        self._audit.append(
            AuditEvent(
                action="pairing.client_revoked",
                actor=requester,
                occurred_at=now,
                details={"client_id": client_id, "name": client.name, "kind": client.kind},
            )
        )

    def authenticate_bearer(self, token: str) -> Client | None:
        return self._verify_credential(self._hasher.hash(token))

    def authenticate_session(self, session_id: str) -> Client | None:
        return self._verify_credential(self._hasher.hash(session_id))

    def _verify_credential(self, credential_hash: str) -> Client | None:
        now = self._clock.now()
        client = self._pairing.find_client_by_credential_hash(credential_hash)
        if client is None or client.revoked_at is not None:
            return None
        if client.kind == "browser":
            last = client.last_seen_at
            if last is None or (now - last) > IDLE_TTL:
                return None
        self._pairing.touch_client(client.id, now)
        return client
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_pairing.py -v`
Expected: PASS (all tests, including the concurrency test against real Postgres)

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/pairing.py dojo-core/tests/test_pairing.py
git commit -m "feat(dojo-core): client listing, revocation, and credential verification (#3)"
```

---

### Task 5: Backend wiring — pairing router, auth dependency, protected routes

**Files:**
- Modify: `backend/src/backend/main.py`
- Modify: `backend/src/backend/deps.py`
- Create: `backend/src/backend/routes/pairing.py`
- Modify: `backend/src/backend/routes/packages.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `DojoPairing`, `Client`, exceptions from Tasks 1-4.
- Produces: `backend.routes.pairing.router` (endpoints below); `backend.deps.get_current_client(request) -> Client` and `backend.deps.build_pairing() -> DojoPairing`; `create_app(publishing=None, pairing=None, cookie_secure=None)`; `app.state.pairing`, `app.state.cookie_secure`; packages router now requires auth.
- Cookie name: `dojo_session`. Endpoints: `POST /api/pairing/codes`, `POST /api/pairing/validate`, `GET /api/pairing/clients`, `POST /api/pairing/clients/{client_id}/revoke`, `GET /api/pairing/me`.

- [ ] **Step 1: Write the failing tests**

Rewrite `backend/tests/test_api.py`:
```python
from __future__ import annotations

from pathlib import Path

from dojo import DojoPairing, DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock
from fastapi.testclient import TestClient

from backend.main import create_app


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
    client = TestClient(create_app(publishing, pairing, cookie_secure=False))
    return client, publishing, pairing


def pair_device(client: TestClient, pairing: DojoPairing, name: str = "Phone") -> str:
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post("/api/pairing/validate", json={"code": code, "kind": "device", "name": name})
    assert resp.status_code == 200
    return resp.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_packages_require_auth(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.get("/api/packages/active").status_code == 401
    assert client.post("/api/packages/active").status_code == 401


def test_paired_device_can_use_packages(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    created = client.post("/api/packages/active", headers=bearer(token))
    assert created.status_code == 201
    fetched = client.get("/api/packages/active", headers=bearer(token))
    assert fetched.status_code == 200


def test_revoked_device_denied_on_next_request(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 201

    clients = client.get("/api/pairing/clients", headers=bearer(token)).json()
    assert len(clients) == 1
    revoke = client.post(f"/api/pairing/clients/{clients[0]['id']}/revoke", headers=bearer(token))
    assert revoke.status_code == 200
    assert client.post("/api/packages/active", headers=bearer(token)).status_code == 401


def test_browser_session_cookie_auth(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post("/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"})
    assert resp.status_code == 200
    assert "dojo_session" in resp.cookies
    cookie = client.cookies.get("dojo_session")
    assert cookie is not None
    assert client.post("/api/packages/active").status_code == 201


def test_browser_validate_sets_secure_http_only_cookie(tmp_path: Path) -> None:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    client = TestClient(create_app(None, pairing, cookie_secure=True))
    code = pairing.create_pairing_code(requester="cli").raw_code
    resp = client.post("/api/pairing/validate", json={"code": code, "kind": "browser", "name": "Browser"})
    header = resp.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "secure" in header


def test_me_returns_current_client(tmp_path: Path) -> None:
    client, _, pairing = make_app(tmp_path)
    token = pair_device(client, pairing)
    me = client.get("/api/pairing/me", headers=bearer(token)).json()
    assert me["kind"] == "device"
    assert me["name"] == "Phone"
    assert client.get("/api/pairing/me").status_code == 401


def test_invalid_code_returns_401(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    resp = client.post("/api/pairing/validate", json={"code": "aaaaaaaa", "kind": "device", "name": "X"})
    assert resp.status_code == 401


def test_unauthenticated_code_minting_rejected(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    assert client.post("/api/pairing/codes").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: FAIL — missing router/dependency, existing routes unauthenticated.

- [ ] **Step 3: Add deps**

`backend/src/backend/deps.py` (full file):
```python
from __future__ import annotations

import os
from pathlib import Path

from dojo import Client, DojoPairing, DojoPublishing
from dojo.adapters.db import PostgresStore
from fastapi import HTTPException, Request

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"


def build_publishing() -> DojoPublishing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(packages=store, audit=store, media_root=media_root)


def build_pairing() -> DojoPairing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoPairing(pairing=store, audit=store)


def get_current_client(request: Request) -> Client:
    pairing: DojoPairing = request.app.state.pairing
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        client = pairing.authenticate_bearer(authorization[7:].strip())
        if client is not None:
            return client
    session_id = request.cookies.get("dojo_session")
    if session_id:
        client = pairing.authenticate_session(session_id)
        if client is not None:
            return client
    raise HTTPException(status_code=401, detail="unauthorized")
```

- [ ] **Step 4: Add the pairing router**

`backend/src/backend/routes/pairing.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from dojo import Client, ClientNotFound, DojoPairing, PairingError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.deps import get_current_client
from dojo.pairing import CODE_TTL

COOKIE_NAME = "dojo_session"
SESSION_MAX_AGE = 30 * 24 * 3600
TTL_SECONDS = int(CODE_TTL.total_seconds())


def get_pairing(request: Request) -> DojoPairing:
    return request.app.state.pairing


router = APIRouter(prefix="/api/pairing", tags=["pairing"])


class CodeOut(BaseModel):
    code: str
    expires_at: datetime
    ttl_seconds: int


class ValidateIn(BaseModel):
    code: str
    kind: Literal["device", "browser"]
    name: str


class ClientOut(BaseModel):
    id: int
    name: str
    kind: str
    created_at: datetime
    created_by: str
    last_seen_at: datetime | None
    revoked_at: datetime | None


@router.post("/codes", response_model=CodeOut)
def create_code(
    requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> CodeOut:
    issued = pairing.create_pairing_code(requester=str(requester.id))
    return CodeOut(code=issued.raw_code, expires_at=issued.expires_at, ttl_seconds=TTL_SECONDS)


@router.post("/validate")
def validate(body: ValidateIn, request: Request, pairing: DojoPairing = Depends(get_pairing)):
    try:
        result = pairing.validate_code(code=body.code, kind=body.kind, name=body.name)
    except PairingError as exc:
        raise HTTPException(status_code=401, detail="invalid pairing code") from exc
    if result.kind == "device":
        return {"client_id": result.client_id, "kind": result.kind, "token": result.raw_credential}
    response = JSONResponse({"client_id": result.client_id, "kind": result.kind})
    response.set_cookie(
        COOKIE_NAME,
        result.raw_credential,
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    return response


@router.get("/clients", response_model=list[ClientOut])
def list_clients(
    _requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> list[ClientOut]:
    return [ClientOut(**vars(c)) for c in pairing.list_clients()]


@router.post("/clients/{client_id}/revoke")
def revoke_client(
    client_id: int,
    requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> dict[str, bool]:
    try:
        pairing.revoke_client(client_id=client_id, requester=str(requester.id))
    except ClientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"revoked": True}


@router.get("/me", response_model=ClientOut)
def me(client: Client = Depends(get_current_client)) -> ClientOut:
    return ClientOut(**vars(client))
```

- [ ] **Step 5: Wire the app and protect packages**

`backend/src/backend/main.py` (full file):
```python
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dojo import DojoPairing, DojoPublishing
from fastapi import Depends, FastAPI

from backend.deps import build_pairing, build_publishing, get_current_client
from backend.routes import health, packages, pairing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not hasattr(app.state, "publishing"):
        app.state.publishing = build_publishing()
    if not hasattr(app.state, "pairing"):
        app.state.pairing = build_pairing()
    yield


def create_app(
    publishing: DojoPublishing | None = None,
    pairing: DojoPairing | None = None,
    cookie_secure: bool | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Dojo publishing API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if publishing is not None:
        app.state.publishing = publishing
    if pairing is not None:
        app.state.pairing = pairing
    if cookie_secure is None:
        cookie_secure = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    app.state.cookie_secure = cookie_secure
    app.include_router(health.router)
    app.include_router(packages.router, dependencies=[Depends(get_current_client)])
    app.include_router(pairing.router)
    return app


app = create_app()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: PASS (9 tests)

- [ ] **Step 7: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v; uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/main.py backend/src/backend/deps.py backend/src/backend/routes/pairing.py backend/src/backend/routes/packages.py backend/tests/test_api.py
git commit -m "feat(backend): pairing routes, auth dependency, protected business routes (#3)"
```

---

### Task 6: Per-IP throttle on the validate endpoint

**Files:**
- Modify: `backend/src/backend/routes/pairing.py`
- Modify: `backend/src/backend/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: router from Task 5.
- Produces: `IpThrottle(limit=10, window=60.0)` stored at `app.state.throttle`; `enforce_throttle` dependency applied to `POST /validate`; over-limit returns `429`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:
```python
def test_validate_throttled_per_ip(tmp_path: Path) -> None:
    client, _, _ = make_app(tmp_path)
    for _ in range(10):
        resp = client.post("/api/pairing/validate", json={"code": "aaaaaaaa", "kind": "device", "name": "X"})
        assert resp.status_code == 401
    resp = client.post("/api/pairing/validate", json={"code": "aaaaaaaa", "kind": "device", "name": "X"})
    assert resp.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project backend pytest backend/tests/test_api.py::test_validate_throttled_per_ip -v`
Expected: FAIL (11th request returns 401, not 429)

- [ ] **Step 3: Add the throttle**

In `backend/src/backend/routes/pairing.py`, add near the top:
```python
import time
from collections import deque
from threading import Lock


class IpThrottle:
    def __init__(self, *, limit: int = 10, window: float = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._attempts.setdefault(ip, deque())
            while window and now - window[0] > self._window:
                window.popleft()
            if len(window) >= self._limit:
                return False
            window.append(now)
            return True
```
and:
```python
def get_throttle(request: Request) -> IpThrottle:
    return request.app.state.throttle


def enforce_throttle(request: Request, throttle: IpThrottle = Depends(get_throttle)) -> None:
    ip = request.client.host if request.client is not None else "unknown"
    if not throttle.allow(ip):
        raise HTTPException(status_code=429, detail="too many attempts")
```
Change the validate decorator to `@router.post("/validate", dependencies=[Depends(enforce_throttle)])`.

In `backend/src/backend/main.py`, add `from backend.routes.pairing import IpThrottle` to the imports at the top, and inside `create_app` add after `app.state.cookie_secure = cookie_secure`:
```python
    app.state.throttle = IpThrottle()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v; uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/pairing.py backend/src/backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): per-IP throttle on pairing validate (#3)"
```

---

### Task 7: Admin CLI bootstrap command

**Files:**
- Create: `backend/src/backend/cli.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `DojoPairing`, `PostgresStore`, `PairingCodeIssued`.
- Produces: `backend.cli.mint_code(pairing: DojoPairing) -> PairingCodeIssued` (requester `"cli"`); `backend.cli.main(argv: list[str] | None = None) -> int` (argparse subcommand `create-code`); console script `dojo-create-pairing-code`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_cli.py`:
```python
from __future__ import annotations

import os

import pytest
from dojo import DojoPairing, InMemoryStore
from dojo.testing import FakeClock

from backend.cli import mint_code


def test_mint_code_audits_cli_actor() -> None:
    store = InMemoryStore()
    pairing = DojoPairing(pairing=store, audit=store, clock=FakeClock())
    issued = mint_code(pairing)
    assert len(issued.raw_code) == 8
    events = [e for e in store.list_recent() if e.action == "pairing.code_created"]
    assert len(events) == 1
    assert events[0].actor == "cli"
```
(Note: `mint_code` is the CLI's only logic — it delegates to
`pairing.create_pairing_code(requester="cli")`. `main()` is a thin
`argparse`+`PostgresStore` wrapper exercised manually in ops; it is not unit
tested because it requires a live `DATABASE_URL`. If you want to exercise it,
run `uv run --project backend python -m backend.cli create-code` against a
running stack and confirm it prints an 8-char code.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_cli.py::test_mint_code_audits_cli_actor -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.cli'`

- [ ] **Step 3: Write the CLI**

`backend/src/backend/cli.py`:
```python
from __future__ import annotations

import argparse
import os

from dojo import DojoPairing
from dojo.adapters.db import PostgresStore
from dojo.model import PairingCodeIssued

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5432/dojo"


def mint_code(pairing: DojoPairing) -> PairingCodeIssued:
    return pairing.create_pairing_code(requester="cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dojo-create-pairing-code")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_URL),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-code")
    args = parser.parse_args(argv)

    store = PostgresStore(args.database_url)
    store.create_all()
    pairing = DojoPairing(pairing=store, audit=store)
    issued = mint_code(pairing)
    print(f"Pairing code: {issued.raw_code}")
    print(f"Expires at:   {issued.expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

In `backend/pyproject.toml`, add under `[project]`:
```toml
[project.scripts]
dojo-create-pairing-code = "backend.cli:main"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v; uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/cli.py backend/pyproject.toml backend/tests/test_cli.py
git commit -m "feat(backend): bootstrap pairing-code CLI (#3)"
```

---

### Task 8: Final verification

**Files:**
- No new files.

- [ ] **Step 1: Run the full workspace checks**

Run: `uv run --project dojo-core pytest dojo-core/tests -v; uv run --project backend pytest backend/tests -v`
Expected: all tests pass (dojo-core domain + store + pairing suites, backend contract + CLI suites).

Run: `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests; uv run --project backend ruff check backend/src backend/tests; uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project backend mypy backend/src/backend`
Expected: no findings.

Run: `uv run --project dojo-core alembic -c dojo-core/alembic.ini heads`
Expected: prints a single head revision chain ending at `0002_pairing` (current heads).

- [ ] **Step 2: Manual acceptance sweep against the ticket**

Confirm each issue #3 acceptance criterion maps to an implemented behavior:
1. One-time code is single-use and enforces expiry → `test_code_is_single_use`, `test_code_expires`, conditional-update consume.
2. Paired device and browser authenticate; equal permissions → `test_pair_device_issues_authenticatable_token`, `test_pair_browser_issues_session`, `test_equal_permissions_any_client_can_mint_and_revoke`.
3. Paired clients listed and revocable; revoked credential denied next request → `test_list_clients_shows_revoked_flag`, `test_revoke_denies_device`, `test_revoke_denies_browser_session`, `test_revoked_device_denied_on_next_request`.
4. Pairing and revocation in audit attributed to acting client → `test_pairing_audited_with_acting_client`, `test_revocation_audited_with_acting_client`.

- [ ] **Step 3: Commit any remaining docs**

If the spec/plan docs were updated during implementation, commit them:
```bash
git add docs
git commit -m "docs: pairing and equal-privilege auth spec + plan (#3)"
```
(Only if there are staged doc changes; otherwise skip.)
