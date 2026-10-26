"""Keep one pending slot per class and one actionable review, preserving history."""

from alembic import op
from sqlalchemy import text

revision = "0020_schedule_uniqueness"
down_revision = "0019_review_publication_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE yayin_zamani, yayin_incelemesi IN SHARE ROW EXCLUSIVE MODE")
    # Due regular rows no longer compete with the one future pending slot.
    op.execute("UPDATE yayin_zamani SET status = 'due' "
               "WHERE kind = 'regular' AND status = 'pending' AND due_at <= now()")
    connection = op.get_bind()
    conflicts = []
    for table, predicate in [
        ("yayin_zamani", "kind = 'regular' AND status = 'pending'"),
        ("yayin_zamani", "kind IN ('manual', 'oneoff') AND status = 'pending'"),
        ("yayin_incelemesi", "status IN ('pending', 'failed', 'uncertain', 'publishing')"),
    ]:
        ids = connection.scalar(text(
            f"SELECT array_agg(id ORDER BY id) FROM {table} WHERE {predicate} HAVING count(*) > 1"
        ))
        if ids:
            conflicts.append(f"{table}: row IDs {ids}")
    if conflicts:
        raise RuntimeError("Schedule uniqueness conflicts; resolve explicitly before upgrade:\n"
                           + "\n".join(conflicts))
    for name, table, column, predicate in [
        ("uq_yayin_zamani_pending_regular", "yayin_zamani", "kind",
         "kind = 'regular' AND status = 'pending'"),
        ("uq_yayin_zamani_pending_exception", "yayin_zamani", "status",
         "kind IN ('manual', 'oneoff') AND status = 'pending'"),
        ("uq_yayin_incelemesi_actionable", "yayin_incelemesi", "(1)",
         "status IN ('pending', 'failed', 'uncertain', 'publishing')"),
    ]:
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({column}) WHERE {predicate}")


def downgrade() -> None:
    op.drop_index("uq_yayin_incelemesi_actionable", table_name="yayin_incelemesi")
    op.drop_index("uq_yayin_zamani_pending_exception", table_name="yayin_zamani")
    op.drop_index("uq_yayin_zamani_pending_regular", table_name="yayin_zamani")
    op.execute("UPDATE yayin_zamani SET status = 'pending' WHERE status = 'due'")
