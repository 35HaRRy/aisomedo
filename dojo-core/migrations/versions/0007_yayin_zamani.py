"""yayin_zamani schedule occurrences table

Revision ID: 0007_yayin_zamani
Revises: 0006_conflict_resolution
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_yayin_zamani"
down_revision: Union[str, None] = "0006_conflict_resolution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "yayin_zamani",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_yayin_zamani_status_due", "yayin_zamani", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_yayin_zamani_status_due", table_name="yayin_zamani")
    op.drop_table("yayin_zamani")
