"""Seed an empty, editable media-consent policy on installation.

Revision ID: 0018_default_consent_policy
Revises: 0017_live_state
Create Date: 2026-10-22

"""
import sqlalchemy as sa
from alembic import op

revision = "0018_default_consent_policy"
down_revision = "0017_live_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO consent_policies (version, text, created_at, created_by) "
            "VALUES (1, 'Görsellerimin paylaşılmasını onaylıyorum.', now(), 'installation') "
            "ON CONFLICT (version) DO NOTHING"
        )
    )


def downgrade() -> None:
    # Only remove the untouched seed; administrators may have replaced its text.
    op.execute(
        sa.text(
            "DELETE FROM consent_policies "
            "WHERE version = 1 AND created_by = 'installation' "
            "AND text = 'Görsellerimin paylaşılmasını onaylıyorum.'"
        )
    )
