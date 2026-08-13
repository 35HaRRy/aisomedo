from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dojo.adapters.db import Base, PostgresStore
from dojo.model import AuditEvent, Package
from dojo.testing import FIXED_AT
from sqlalchemy import inspect


def test_create_and_get_active(pg_store: PostgresStore) -> None:
    created = pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))

    assert created.id > 0
    assert created.folder_name == "06-08-2026 14-30"
    assert pg_store.get_active() == created


def test_get_active_returns_none_when_empty(pg_store: PostgresStore) -> None:
    assert pg_store.get_active() is None


def test_folder_name_is_unique(pg_store: PostgresStore) -> None:
    pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))
    with pytest.raises(Exception):  # sqlalchemy IntegrityError on commit
        pg_store.create(Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT))


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


def test_list_recent_respects_limit(pg_store: PostgresStore) -> None:
    for i in range(5):
        pg_store.append(
            AuditEvent(action="x", actor="system", occurred_at=FIXED_AT, details={"i": i})
        )
    assert len(pg_store.list_recent(limit=2)) == 2


def test_alembic_upgrade_head_creates_schema(pg_store: PostgresStore, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option(
        "sqlalchemy.url", pg_store._engine.url.render_as_string(hide_password=False)  # noqa: SLF001
    )

    with pg_store._engine.begin() as conn:  # noqa: SLF001
        Base.metadata.drop_all(conn)
    command.upgrade(cfg, "head")

    inspector = inspect(pg_store._engine)  # noqa: SLF001
    assert {"packages", "audit_events", "consent_policies", "consent_acceptances"} <= set(
        inspector.get_table_names()
    )
    package_indexes = {i["name"] for i in inspector.get_indexes("packages")}
    assert "ix_packages_status_active" in package_indexes
