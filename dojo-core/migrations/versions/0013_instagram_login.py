"""Support Instagram Login connections without Facebook pages or known expiry."""

import sqlalchemy as sa
from alembic import op

revision = "0013_instagram_login"
down_revision = "0012_meta_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meta_connections", sa.Column(
        "connection_type", sa.String(32), nullable=False, server_default="facebook_login",
    ))
    op.alter_column("meta_connections", "page_id", existing_type=sa.Text(), nullable=True)
    op.alter_column("meta_connections", "page_name", existing_type=sa.Text(), nullable=True)
    op.alter_column(
        "meta_connections", "token_expires_at", existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    # Refuse rollback rather than invent a Facebook page or discard a saved token.
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM meta_connections WHERE connection_type <> 'facebook_login' "
        "OR page_id IS NULL OR page_name IS NULL OR token_expires_at IS NULL"
    )).scalar_one()
    if count:
        raise RuntimeError("Reconnect with Facebook Login before downgrading this migration")
    op.alter_column("meta_connections", "page_id", existing_type=sa.Text(), nullable=False)
    op.alter_column("meta_connections", "page_name", existing_type=sa.Text(), nullable=False)
    op.alter_column(
        "meta_connections", "token_expires_at", existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.drop_column("meta_connections", "connection_type")
