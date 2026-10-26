"""Authoritative package documents and transaction-bound live invalidations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017_live_state"
down_revision = "0016_monitoring_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "package_states",
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("content_revision", sa.BigInteger(), nullable=False),
        sa.Column("view_revision", sa.BigInteger(), nullable=False),
        sa.Column("document", JSONB(), nullable=False),
        sa.CheckConstraint("content_revision > 0 AND view_revision > 0",
                           name="ck_package_states_revisions"),
    )
    op.create_table(
        "live_resource_versions",
        sa.Column("resource", sa.String(255), primary_key=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("version >= 0", name="ck_live_resource_version"),
    )
    op.create_table(
        "live_change_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("versions", JSONB(), nullable=False),
        sa.Column("revoked_client_ids", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("live_change_events")
    op.drop_table("live_resource_versions")
    op.drop_table("package_states")
