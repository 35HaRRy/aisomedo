"""consent_policies and consent_acceptances

Revision ID: 0003_setup
Revises: 0002_pairing
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_setup"
down_revision: Union[str, None] = "0002_pairing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consent_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=4096), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_consent_policies_version", "consent_policies", ["version"])
    op.create_table(
        "consent_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepting_client_id", sa.Integer(), nullable=False),
        sa.Column("accepting_client_name", sa.String(length=128), nullable=False),
        sa.Column("accepting_client_kind", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("policy_version"),
    )
    op.create_index(
        "ix_consent_acceptances_policy_version", "consent_acceptances", ["policy_version"]
    )


def downgrade() -> None:
    op.drop_index("ix_consent_acceptances_policy_version", table_name="consent_acceptances")
    op.drop_table("consent_acceptances")
    op.drop_index("ix_consent_policies_version", table_name="consent_policies")
    op.drop_table("consent_policies")