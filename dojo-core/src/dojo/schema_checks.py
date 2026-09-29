"""Read-only migration preflight and conservative legacy schema recognition."""

from __future__ import annotations

import re

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, MetaData, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector

EMISSION_INDEXES = {"uq_jobs_active_render", "uq_yayin_zamani_regular_due"}
MONITORING_TABLES = {"monitoring_incidents", "operational_alerts", "operational_deliveries"}
MONITORING_INDEXES = {"ix_operational_deliveries_due"}
MONITORING_CHECKS = {
    "ck_operational_alerts_kind",
    "ck_operational_deliveries_status",
    "ck_operational_deliveries_attempts",
}


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


def _check_sqltext(inspector: Inspector, table: str, name: str) -> str | None:
    """The reflected CHECK body for ``name``, or None if the table has none."""
    for check in inspector.get_check_constraints(table):
        if check["name"] == name:
            return str(check["sqltext"])
    return None


def _predicate(value: object) -> str:
    # PostgreSQL adds casts/parentheses when deparsing index predicates.
    result = re.sub(r"::(?:text|character varying)(?:\[\])?", "", str(value))
    result = re.sub(r"[\s()]", "", result)
    # PostgreSQL deparses IN lists as = ANY (ARRAY[...]).
    return re.sub(r"=ANYARRAY\[(.*?)\]", r"IN\1", result)


OLDEST_BASELINE = "0013_instagram_login"
EMISSION_REVISION = "0014_emission_idempotency"
MONITORING_REVISION = "0015_operational_monitoring"
MONITORING_CHECKS_REVISION = "0016_monitoring_checks"


def _is_pending_monitoring(difference: tuple) -> bool:
    """True for exactly the objects revision 0015 adds to a pre-0015 schema."""
    if difference[0] == "add_table" and difference[1].name in MONITORING_TABLES:
        return True
    if difference[0] == "add_index" and difference[1].name in MONITORING_INDEXES:
        return True
    # compare_metadata tuples carry a schema slot before the table name.
    return difference[0] == "add_column" and difference[2] == "jobs" \
        and difference[3].name == "failure_generation"


def _is_pending_check(difference: tuple) -> bool:
    """True for exactly the constraints revision 0016 adds."""
    if difference[0] != "add_constraint" or not isinstance(difference[1], CheckConstraint):
        return False
    return difference[1].name in MONITORING_CHECKS


def validate_legacy_schema(connection: Connection) -> str:
    """Recognize an unversioned create_all schema and return the revision to stamp.

    Two shapes are recognized: the current create_all schema, and the
    pre-0015 shape it is expected to still be missing 0015's objects from. Any
    other difference in columns/types/nullability/defaults, keys, foreign keys,
    indexes or predicates is rejected before stamping. Keep this baseline
    validator in sync deliberately when future models change.
    """
    from dojo.adapters.db import Base

    inspector = inspect(connection)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    if tables not in (set(Base.metadata.tables), set(Base.metadata.tables) - MONITORING_TABLES):
        raise RuntimeError("Unsupported unversioned schema: table set differs from baseline")
    indexes = {
        table: {index["name"]: index for index in inspector.get_indexes(table)}
        for table in tables
    }
    checks = {
        table: {check["name"] for check in inspector.get_check_constraints(table)}
        for table in tables
    }
    pending_monitoring = not MONITORING_TABLES <= tables
    # 0016 only adds constraints, so a 0015 shape is recognized by their absence
    # and stamped accordingly: create_all already has them, a 0015 database
    # must still run 0016 rather than collide with it.
    pending_checks = not MONITORING_CHECKS <= {
        name for group in checks.values() for name in group
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
        if table.name not in tables:
            continue  # 0015 creates these; only the objects above are pending.
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
        # compare_metadata does not compare CHECK bodies, so a constraint kept
        # under the expected name but with a weaker predicate would pass review.
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            name = constraint.name
            if not isinstance(name, str):
                continue  # Unnamed CHECK: compare_metadata's business, not ours.
            if name in MONITORING_CHECKS and pending_checks:
                continue  # 0016 adds this one.
            actual_sql = _check_sqltext(inspector, table.name, name)
            if actual_sql is None:
                continue  # Already reported as a difference by compare_metadata.
            if _predicate(constraint.sqltext) != _predicate(actual_sql):
                differences.append(("check_predicate", table.name, name))
    if pending_monitoring:
        differences = [d for d in differences if not _is_pending_monitoring(d)]
    if pending_checks:
        differences = [d for d in differences if not _is_pending_check(d)]
    if differences:
        raise RuntimeError(f"Unsupported unversioned schema: {differences!r}")
    if pending_monitoring:
        return EMISSION_REVISION if present else OLDEST_BASELINE
    if pending_checks:
        return MONITORING_REVISION if present else EMISSION_REVISION
    return MONITORING_CHECKS_REVISION if present else MONITORING_REVISION
