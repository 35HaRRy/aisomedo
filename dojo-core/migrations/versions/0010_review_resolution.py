"""yayin_incelemesi review resolution fields

Revision ID: 0010_review_resolution
Revises: 0009_jobs_upload_nullable
Create Date: 2026-08-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_review_resolution"
down_revision: Union[str, None] = "0009_jobs_upload_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "yayin_incelemesi",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "yayin_incelemesi",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "yayin_incelemesi",
        sa.Column("resolved_by", sa.Text(), nullable=True),
    )
    op.add_column(
        "yayin_incelemesi",
        sa.Column("oneoff_occurrence_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("yayin_incelemesi", "oneoff_occurrence_id")
    op.drop_column("yayin_incelemesi", "resolved_by")
    op.drop_column("yayin_incelemesi", "resolved_at")
    op.drop_column("yayin_incelemesi", "version")