"""Enforce regular due-time and active render identity without deleting history."""

import sqlalchemy as sa
from alembic import op
from dojo.schema_checks import preflight_emission_conflicts

revision = "0014_emission_idempotency"
down_revision = "0013_instagram_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Block concurrent writes between preflight and index creation, including
    # callers using Alembic directly instead of the serialized initializer.
    op.execute("LOCK TABLE yayin_zamani, jobs, yayin_incelemesi IN SHARE MODE")
    preflight_emission_conflicts(op.get_bind())
    op.create_index("uq_yayin_zamani_regular_due", "yayin_zamani", ["due_at"],
                    unique=True, postgresql_where=sa.text("kind = 'regular'"))
    op.create_index(
        "uq_jobs_active_render", "jobs",
        [sa.text("(payload ->> 'package')"), sa.text("(payload ->> 'digest')")],
        unique=True,
        postgresql_where=sa.text("kind = 'render' AND status IN ('queued', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_active_render", table_name="jobs")
    op.drop_index("uq_yayin_zamani_regular_due", table_name="yayin_zamani")
