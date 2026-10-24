"""Store Instagram publication errors on reviews."""
from alembic import op

revision = "0019_review_publication_status"
down_revision = "0018_default_consent_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy create_all installations may already contain the current model column.
    op.execute("ALTER TABLE yayin_incelemesi ADD COLUMN IF NOT EXISTS instagram_fail_message TEXT")


def downgrade() -> None:
    op.drop_column("yayin_incelemesi", "instagram_fail_message")
