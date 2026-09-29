"""Constrain operational alert kind and delivery state at the database

Revision ID: 0016_monitoring_checks
Revises: 0015_operational_monitoring
Create Date: 2026-09-30

A typo in either adapter would otherwise persist a delivery nothing ever claims
again, or an alert no client recognizes. PostgreSQL CHECK constraints cannot be
DEFERRABLE, so these take a short table lock; the tables are small and only
written by the monitoring collector.
"""

from typing import Sequence, Union

from alembic import op
from dojo.monitoring_models import (
    ALERT_KIND_CHECK,
    DELIVERY_ATTEMPTS_CHECK,
    DELIVERY_STATUS_CHECK,
)

revision: str = "0016_monitoring_checks"
down_revision: Union[str, None] = "0015_operational_monitoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_operational_alerts_kind", "operational_alerts", ALERT_KIND_CHECK,
    )
    op.create_check_constraint(
        "ck_operational_deliveries_status", "operational_deliveries", DELIVERY_STATUS_CHECK,
    )
    op.create_check_constraint(
        "ck_operational_deliveries_attempts", "operational_deliveries",
        DELIVERY_ATTEMPTS_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_operational_deliveries_attempts", "operational_deliveries", type_="check",
    )
    op.drop_constraint(
        "ck_operational_deliveries_status", "operational_deliveries", type_="check",
    )
    op.drop_constraint("ck_operational_alerts_kind", "operational_alerts", type_="check")
