"""yayin_incelemesi durable review table

Revision ID: 0008_yayin_incelemesi
Revises: 0007_yayin_zamani
Create Date: 2026-08-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_yayin_incelemesi"
down_revision: Union[str, None] = "0007_yayin_zamani"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "yayin_incelemesi",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurrence_id", sa.Integer(), nullable=False),
        sa.Column("package_folder", sa.Text(), nullable=False),
        sa.Column("revision_digest", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "occurrence_id", "revision_digest", name="uq_yayin_incelemesi_occ_rev"
        ),
    )
    op.create_index(
        "ix_yayin_incelemesi_status", "yayin_incelemesi", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_yayin_incelemesi_status", table_name="yayin_incelemesi")
    op.drop_table("yayin_incelemesi")