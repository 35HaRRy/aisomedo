from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dojo.adapters.db import Base, PostgresStore
from dojo.model import AuditEvent, Package, YayinIncelemesi, YayinZamani
from dojo.testing import FIXED_AT
from sqlalchemy import inspect, text


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
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(cfg, "head")

    inspector = inspect(pg_store._engine)  # noqa: SLF001
    assert {"packages", "audit_events", "consent_policies", "consent_acceptances",
            "uploads", "jobs", "settings"} <= set(inspector.get_table_names())
    package_indexes = {i["name"] for i in inspector.get_indexes("packages")}
    assert "ix_packages_status_active" in package_indexes


def _review(
    pg_store: PostgresStore, occurrence_id: int, digest: str, status: str = "pending"
) -> YayinIncelemesi:
    return pg_store.create(
        YayinIncelemesi(
            id=0,
            occurrence_id=occurrence_id,
            package_folder="06-08-2026 14-30",
            revision_digest=digest,
            caption=None,
            status=status,
            created_at=FIXED_AT,
        )
    )


def test_review_create_get_by_occurrence_and_pending(pg_store: PostgresStore) -> None:
    occ = pg_store.create(
        YayinZamani(id=0, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    review = _review(pg_store, occ.id, "digest-a")

    assert review.id > 0
    assert pg_store.get_by_occurrence_revision(occ.id, "digest-a") == review
    assert pg_store.list_pending() == [review]


def test_review_unique_occurrence_revision(pg_store: PostgresStore) -> None:
    occ = pg_store.create(
        YayinZamani(id=0, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    _review(pg_store, occ.id, "digest-a")
    with pytest.raises(Exception):  # sqlalchemy IntegrityError on unique constraint
        _review(pg_store, occ.id, "digest-a")


def test_review_different_revision_allowed(pg_store: PostgresStore) -> None:
    occ = pg_store.create(
        YayinZamani(id=0, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    _review(pg_store, occ.id, "digest-a")
    _review(pg_store, occ.id, "digest-b")
    assert pg_store.list_pending()[0].occurrence_id == occ.id
    assert len(pg_store.list_pending()) == 2


def test_resolve_if_pending_cas_win_then_lose(pg_store: PostgresStore) -> None:
    occ = pg_store.create(
        YayinZamani(id=0, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    review = _review(pg_store, occ.id, "digest-a")
    assert review.version == 1

    won = pg_store.resolve_if_pending(review.id, 1, "approved", FIXED_AT, "A")
    assert won is not None
    assert won.status == "approved"
    assert won.resolved_by == "A"
    assert won.resolved_at == FIXED_AT
    assert won.version == 2

    lost = pg_store.resolve_if_pending(review.id, 1, "skipped", FIXED_AT, "B")
    assert lost is None
    # stale version also loses
    assert pg_store.resolve_if_pending(review.id, won.version, "skipped", FIXED_AT, "B") is None


def test_resolve_if_pending_missing_review(pg_store: PostgresStore) -> None:
    assert pg_store.resolve_if_pending(999, 1, "approved", FIXED_AT, "A") is None


def test_review_update_persists_oneoff_occurrence_id(pg_store: PostgresStore) -> None:
    occ = pg_store.create(
        YayinZamani(id=0, kind="regular", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    review = _review(pg_store, occ.id, "digest-a")

    updated = pg_store.update(replace(review, oneoff_occurrence_id=42))

    assert updated.oneoff_occurrence_id == 42
    assert pg_store.get(review.id) == updated


def test_next_regular_after_skips_non_regular(pg_store: PostgresStore) -> None:
    pg_store.create(
        YayinZamani(id=0, kind="manual", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    pg_store.create(
        YayinZamani(id=0, kind="oneoff", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    future = FIXED_AT.replace(year=2027)
    occ = pg_store.create(
        YayinZamani(id=0, kind="regular", due_at=future, status="pending", created_at=FIXED_AT)
    )

    assert pg_store.next_regular_after(FIXED_AT) == occ


def test_next_regular_after_none_when_no_regular(pg_store: PostgresStore) -> None:
    pg_store.create(
        YayinZamani(id=0, kind="oneoff", due_at=FIXED_AT, status="pending", created_at=FIXED_AT)
    )
    assert pg_store.next_regular_after(FIXED_AT) is None


def test_alembic_upgrade_head_creates_review_resolution_columns(
    pg_store: PostgresStore, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option(
        "sqlalchemy.url", pg_store._engine.url.render_as_string(hide_password=False)  # noqa: SLF001
    )

    with pg_store._engine.begin() as conn:  # noqa: SLF001
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(cfg, "head")

    inspector = inspect(pg_store._engine)  # noqa: SLF001
    review_cols = {c["name"] for c in inspector.get_columns("yayin_incelemesi")}
    assert {"version", "resolved_at", "resolved_by", "oneoff_occurrence_id"} <= review_cols
