"""jobs.upload_id nullable for render jobs

Revision ID: 0009_jobs_upload_nullable
Revises: 0008_yayin_incelemesi
Create Date: 2026-08-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_jobs_upload_nullable"
down_revision: Union[str, None] = "0008_yayin_incelemesi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("jobs", "upload_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("jobs", "upload_id", existing_type=sa.BigInteger(), nullable=False)