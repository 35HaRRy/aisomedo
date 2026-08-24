"""meta connection and oauth attempts

Revision ID: 0012_meta_connection
Revises: 0011_pending_review_notify
Create Date: 2026-08-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_meta_connection"
down_revision: Union[str, None] = "0011_pending_review_notify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ig_user_id", sa.Text(), nullable=False),
        sa.Column("ig_username", sa.Text(), nullable=False),
        sa.Column("page_id", sa.Text(), nullable=False),
        sa.Column("page_name", sa.Text(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("health", sa.String(length=32), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "meta_oauth_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("initiated_by_client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("return_uri", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("encrypted_temp_token", sa.Text(), nullable=True),
        sa.Column("temp_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_meta_oauth_state_hash", "meta_oauth_attempts", ["state_hash"], unique=True)
    op.create_index("ix_meta_oauth_expires_at", "meta_oauth_attempts", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_meta_oauth_expires_at", table_name="meta_oauth_attempts")
    op.drop_index("ix_meta_oauth_state_hash", table_name="meta_oauth_attempts")
    op.drop_table("meta_oauth_attempts")
    op.drop_table("meta_connections")
