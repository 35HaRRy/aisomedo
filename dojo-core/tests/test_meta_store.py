from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from dojo.adapters.db import Base, PostgresStore
from sqlalchemy import text

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def test_instagram_connection_survives_database_roundtrip_and_health_updates(pg_store):
    pg_store.upsert_active(
        ig_user_id="178414000000001", ig_username="dojo", page_id=None, page_name=None,
        encrypted_token="encrypted", token_expires_at=None, health="healthy",
        last_checked_at=NOW, last_refreshed_at=None, last_error=None,
        connection_type="instagram_login",
    )
    reopened = PostgresStore(pg_store._engine.url.render_as_string(hide_password=False))
    try:
        status = reopened.get_meta_status()
        assert status.connection_type == "instagram_login"
        assert status.page_id is None and status.expires_at is None
        assert reopened.get_raw_active() == ("encrypted", None)
        updated = reopened.update_health("refresh_due", NOW, "temporary")
        assert updated.connection_type == "instagram_login"
        updated = reopened.update_token("renewed", NOW + timedelta(days=60), NOW)
        assert updated.connection_type == "instagram_login"
        status = reopened.get_meta_status()
        assert status.connection_type == "instagram_login"
        assert status.expires_at == NOW + timedelta(days=60)
    finally:
        reopened.dispose()


def test_migration_preserves_existing_facebook_connection(pg_store):
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option(
        "sqlalchemy.url", pg_store._engine.url.render_as_string(hide_password=False)
    )
    with pg_store._engine.begin() as connection:
        Base.metadata.drop_all(connection)
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(cfg, "0012_meta_connection")
    with pg_store._engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO meta_connections
                (id, ig_user_id, ig_username, page_id, page_name, encrypted_token,
                 token_expires_at, health)
            VALUES (1, 'old-ig', 'old-user', 'page', 'Page', 'old-cipher', :expiry, 'healthy')
        """), {"expiry": NOW + timedelta(days=60)})
    command.upgrade(cfg, "head")
    status = pg_store.get_meta_status()
    assert getattr(status, "connection_type", None) == "facebook_login"
    assert status.ig_user_id == "old-ig"
    assert pg_store.get_raw_active()[0] == "old-cipher"


def test_stale_worker_cannot_update_replaced_database_connection(pg_store):
    def connect(token):
        pg_store.upsert_active(
            ig_user_id="178414000000001", ig_username="dojo", page_id=None, page_name=None,
            encrypted_token=token, token_expires_at=None, health="healthy",
            last_checked_at=NOW, last_refreshed_at=None, last_error=None,
            connection_type="instagram_login",
        )

    connect("old-cipher")
    connect("new-cipher")
    health = pg_store.update_health(
        "reconnect_required", NOW, "old token failed", expected_encrypted_token="old-cipher"
    )
    token = pg_store.update_token(
        "stale-refresh", NOW + timedelta(days=60), NOW, expected_encrypted_token="old-cipher"
    )
    assert health is None and token is None
    assert pg_store.get_meta_status().health == "healthy"
    assert pg_store.get_raw_active() == ("new-cipher", None)
