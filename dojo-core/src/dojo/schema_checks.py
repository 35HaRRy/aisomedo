"""Read-only migration preflight and conservative legacy schema recognition."""

from __future__ import annotations

import re

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Connection

EMISSION_INDEXES = {"uq_jobs_active_render", "uq_yayin_zamani_regular_due"}


def preflight_emission_conflicts(connection: Connection) -> None:
    """Report all conflicting row IDs, never repair or discard historical data."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    conflicts = []
    queries = [
        ("yayin_zamani", {"id", "kind", "due_at"}, """
            SELECT array_agg(id ORDER BY id) AS ids FROM yayin_zamani
            WHERE kind = 'regular' GROUP BY due_at HAVING count(*) > 1
        """),
        ("jobs", {"id", "kind", "status", "payload"}, """
            SELECT array_agg(id ORDER BY id) AS ids FROM jobs
            WHERE kind = 'render' AND status IN ('queued', 'processing')
              AND payload ->> 'package' IS NOT NULL AND payload ->> 'digest' IS NOT NULL
            GROUP BY payload ->> 'package', payload ->> 'digest' HAVING count(*) > 1
        """),
        ("yayin_incelemesi", {"id", "occurrence_id", "revision_digest"}, """
            SELECT array_agg(id ORDER BY id) AS ids FROM yayin_incelemesi
            GROUP BY occurrence_id, revision_digest HAVING count(*) > 1
        """),
    ]
    for table, required, query in queries:
        if table not in tables:
            continue
        if not required <= {c["name"] for c in inspector.get_columns(table)}:
            continue  # Structural validation will reject this unsupported schema.
        for ids in connection.execute(text(query)).scalars():
            conflicts.append(f"{table}: row IDs {ids}")
    if conflicts:
        raise RuntimeError("Emission uniqueness conflicts; resolve explicitly before upgrade:\n"
                           + "\n".join(conflicts))


def _predicate(value: object) -> str:
    # PostgreSQL adds casts/parentheses when deparsing index predicates.
    result = re.sub(r"::(?:text|character varying)(?:\[\])?", "", str(value))
    result = re.sub(r"[\s()]", "", result)
    # PostgreSQL deparses IN lists as = ANY (ARRAY[...]).
    return re.sub(r"=ANYARRAY\[(.*?)\]", r"IN\1", result)


def validate_legacy_schema(connection: Connection) -> bool:
    """Recognize the 0013 create_all schema, optionally with both 0014 indexes.

    Reject differences in columns/types/nullability/defaults, keys, foreign keys,
    indexes and predicates before stamping. Return whether 0014 is already present.
    Keep this baseline validator in sync deliberately when future models change.
    """
    from dojo.adapters.db import Base

    inspector = inspect(connection)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    if tables != set(Base.metadata.tables):
        raise RuntimeError("Unsupported unversioned schema: table set differs from baseline")
    indexes = {
        table: {index["name"]: index for index in inspector.get_indexes(table)}
        for table in tables
    }
    present = EMISSION_INDEXES & {name for group in indexes.values() for name in group}
    if present and present != EMISSION_INDEXES:
        raise RuntimeError("Unsupported unversioned schema: incomplete emission indexes")
    expected = MetaData()
    for table in Base.metadata.sorted_tables:
        copied = table.to_metadata(expected)
        for index in list(copied.indexes):
            if index.name in EMISSION_INDEXES and not present:
                copied.indexes.remove(index)
    differences = compare_metadata(MigrationContext.configure(connection, opts={
        "compare_type": True, "compare_server_default": True,
    }), expected)
    for table in expected.sorted_tables:
        primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
        if primary_key != [c.name for c in table.primary_key.columns]:
            differences.append(("primary_key", table.name))
        for index in table.indexes:
            actual = indexes[table.name].get(index.name)
            if actual is None:
                continue  # Already reported by compare_metadata.
            predicate = index.dialect_options["postgresql"].get("where")
            actual_predicate = actual.get("dialect_options", {}).get("postgresql_where")
            if _predicate(predicate) != _predicate(actual_predicate):
                differences.append(("index_predicate", table.name, index.name))
    if differences:
        raise RuntimeError(f"Unsupported unversioned schema: {differences!r}")
    return bool(present)
