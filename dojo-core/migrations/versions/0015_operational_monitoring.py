"""Durable operational monitoring: failure events, disk incidents, deliveries

Revision ID: 0015_operational_monitoring
Revises: 0014_emission_idempotency
Create Date: 2026-09-30

Existing failed jobs are reported once with generation 1 so that activation
covers history without re-alerting on every scan.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from dojo.monitoring_models import job_failure_alert, job_failure_event_key
from sqlalchemy.dialects.postgresql import insert as pg_insert
from uuid import uuid4

revision: str = "0015_operational_monitoring"
down_revision: Union[str, None] = "0014_emission_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALERTS = sa.table(
    "operational_alerts",
    sa.column("alert_id", sa.String),
    sa.column("event_key", sa.String),
    sa.column("kind", sa.String),
    sa.column("title", sa.String),
    sa.column("body", sa.String),
    sa.column("data", sa.JSON),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("recipients_snapshotted_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("failure_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "monitoring_incidents",
        sa.Column("target", sa.String(length=64), primary_key=True),
        sa.Column("active_incident_id", sa.String(length=36), nullable=True),
        sa.Column("last_sampled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "operational_alerts",
        sa.Column("alert_id", sa.String(length=36), primary_key=True),
        sa.Column("event_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("body", sa.String(length=512), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipients_snapshotted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "operational_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "alert_id", sa.String(length=36),
            sa.ForeignKey("operational_alerts.alert_id"), nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("claim_id", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "alert_id", "client_id", name="uq_operational_deliveries_alert_client",
        ),
    )
    op.create_index(
        "ix_operational_deliveries_due", "operational_deliveries", ["status", "due_at"],
    )
    _backfill_failed_jobs(op.get_bind())


def _backfill_failed_jobs(bind) -> None:
    """One alert per already failed job, at generation 1, from the same builders."""
    bind.execute(sa.text("UPDATE jobs SET failure_generation = 1 WHERE status = 'failed'"))
    failed = bind.execute(sa.text(
        "SELECT job_id, kind, COALESCE(finished_at, created_at) AS failed_at"
        "  FROM jobs WHERE status = 'failed' ORDER BY id"
    )).all()
    for job_id, kind, failed_at in failed:
        alert = job_failure_alert(
            alert_id=str(uuid4()),
            event_key=job_failure_event_key(job_id, 1),
            job_id=job_id,
            kind=kind,
            created_at=failed_at,
        )
        bind.execute(
            pg_insert(ALERTS).values(
                alert_id=alert.alert_id,
                event_key=alert.event_key,
                kind=alert.kind,
                title=alert.title,
                body=alert.body,
                data=alert.data,
                created_at=alert.created_at,
                recipients_snapshotted_at=None,
            ).on_conflict_do_nothing(index_elements=[ALERTS.c.event_key])
        )


def downgrade() -> None:
    op.drop_index("ix_operational_deliveries_due", table_name="operational_deliveries")
    op.drop_table("operational_deliveries")
    op.drop_table("operational_alerts")
    op.drop_table("monitoring_incidents")
    op.drop_column("jobs", "failure_generation")
