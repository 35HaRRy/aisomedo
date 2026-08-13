"""partial unique index on active packages

Revision ID: 0004_active_package
Revises: 0003_setup
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_active_package"
down_revision: Union[str, None] = "0003_setup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_packages_status_active",
        "packages",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_packages_status_active", table_name="packages")
