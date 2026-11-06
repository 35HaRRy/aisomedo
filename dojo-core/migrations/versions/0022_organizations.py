"""Attach existing workspaces to Kaizen without changing identities or media paths."""

import sqlalchemy as sa
from alembic import op

revision = "0022_organizations"
down_revision = "0021_media_preview_jobs"
branch_labels = None
depends_on = None

OWNED = (
    "packages", "audit_events", "pairing_codes", "clients", "uploads", "jobs",
    "settings", "yayin_zamani", "yayin_incelemesi", "meta_connections",
    "meta_oauth_attempts", "consent_acceptances", "live_resource_versions",
    "live_change_events", "package_states", "push_registrations",
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    connection = op.get_bind()
    initial = connection.scalar(sa.text("""INSERT INTO organizations (name, name_key, email)
        VALUES ('Kaizen Aikido Akademi', 'kaizen aikido akademi',
                'kaizenaikidoakademi@gmail.com') RETURNING id"""))
    for table in OWNED:
        op.add_column(table, sa.Column("organization_id", sa.Integer(), nullable=True))
        connection.execute(sa.text(f"UPDATE {table} SET organization_id = :id"), {"id": initial})
        op.alter_column(table, "organization_id", nullable=False)
        op.create_foreign_key(f"fk_{table}_organization", table, "organizations",
                              ["organization_id"], ["id"])
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])

    op.add_column("operational_alerts", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_operational_alerts_organization", "operational_alerts",
                          "organizations", ["organization_id"], ["id"])
    op.create_index("ix_operational_alerts_organization_id", "operational_alerts", ["organization_id"])
    connection.execute(sa.text("""UPDATE operational_alerts SET organization_id = :id
        WHERE kind = 'job.failed'"""), {"id": initial})

    for table, keys in (("settings", ["organization_id", "key"]),
                        ("live_resource_versions", ["organization_id", "resource"])):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, keys)

    # A connection used to be a global singleton (id=1); its owner is now the key.
    op.create_unique_constraint("uq_meta_connections_organization", "meta_connections",
                                ["organization_id"])
    op.drop_constraint("packages_folder_name_key", "packages", type_="unique")
    op.create_unique_constraint("uq_packages_organization_folder", "packages",
                                ["organization_id", "folder_name"])
    op.drop_index("uq_jobs_active_render", table_name="jobs")
    op.execute("""CREATE UNIQUE INDEX uq_jobs_active_render
        ON jobs (organization_id, (payload ->> 'package'), (payload ->> 'digest'))
        WHERE kind = 'render' AND status IN ('queued', 'processing')""")
    op.drop_index("uq_jobs_active_media_preview", table_name="jobs")
    op.execute("""CREATE UNIQUE INDEX uq_jobs_active_media_preview
        ON jobs (organization_id, kind, (payload ->> 'package_id'), (payload ->> 'media_id'))
        WHERE kind IN ('section_preview', 'thumbnail') AND status IN ('queued', 'processing')""")
    op.drop_index("ix_consent_acceptances_policy_version", table_name="consent_acceptances")
    op.create_index("ix_consent_acceptances_policy_version", "consent_acceptances",
                    ["organization_id", "policy_version"], unique=True)

    indexes = (
        ("packages", "ix_packages_status_active", ["organization_id", "status"],
         "status = 'active'"),
        ("yayin_zamani", "uq_yayin_zamani_regular_due", ["organization_id", "due_at"],
         "kind = 'regular'"),
        ("yayin_zamani", "uq_yayin_zamani_pending_regular", ["organization_id", "kind"],
         "kind = 'regular' AND status = 'pending'"),
        ("yayin_zamani", "uq_yayin_zamani_pending_exception", ["organization_id", "status"],
         "kind IN ('manual', 'oneoff') AND status = 'pending'"),
        ("yayin_incelemesi", "uq_yayin_incelemesi_actionable", ["organization_id"],
         "status IN ('pending', 'failed', 'uncertain', 'publishing')"),
    )
    for table, name, columns, predicate in indexes:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, columns, unique=True, postgresql_where=sa.text(predicate))

    # Keep existing FK guarantees, also rejecting cross-organization references.
    for table, column in (("packages", "id"), ("clients", "id"), ("uploads", "id")):
        op.create_unique_constraint(f"uq_{table}_organization_identity", table,
                                    ["organization_id", column])
    for table, column, parent, ondelete in (
        ("uploads", "package_id", "packages", None),
        ("jobs", "upload_id", "uploads", None),
        ("package_states", "package_id", "packages", "CASCADE"),
        ("push_registrations", "client_id", "clients", None),
        ("meta_oauth_attempts", "initiated_by_client_id", "clients", None),
    ):
        op.create_foreign_key(f"fk_{table}_organization_parent", table, parent,
                              ["organization_id", column], ["organization_id", "id"],
                              ondelete=ondelete)


def downgrade() -> None:
    raise RuntimeError("Organization migration cannot safely downgrade; restore a pre-upgrade backup")
