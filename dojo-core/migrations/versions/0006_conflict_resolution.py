"""filename conflict resolution columns on uploads

Revision ID: 0006_conflict_resolution
Revises: 0005_media_upload
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_conflict_resolution"
down_revision: Union[str, None] = "0005_media_upload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploads", sa.Column("conflict_decision", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "uploads",
        sa.Column("conflict_target_media_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("uploads", "conflict_target_media_id")
    op.drop_column("uploads", "conflict_decision")
