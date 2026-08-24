"""push registrations and reminder cadence

Revision ID: 0011_pending_review_notifications
Revises: 0010_review_resolution
Create Date: 2026-08-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_pending_review_notifications"
down_revision: Union[str, None] = "0010_review_resolution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "yayin_incelemesi",
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "push_registrations",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), primary_key=True),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("push_registrations")
    op.drop_column("yayin_incelemesi", "last_reminded_at")
