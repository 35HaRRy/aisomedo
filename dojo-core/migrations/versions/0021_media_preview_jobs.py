"""Deduplicate active per-media preview jobs without changing terminal history."""

from alembic import op

revision = "0021_media_preview_jobs"
down_revision = "0020_schedule_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_media_preview
        ON jobs (kind, (payload ->> 'package_id'), (payload ->> 'media_id'))
        WHERE kind IN ('section_preview', 'thumbnail')
          AND status IN ('queued', 'processing')""")


def downgrade() -> None:
    op.drop_index("uq_jobs_active_media_preview", table_name="jobs")
