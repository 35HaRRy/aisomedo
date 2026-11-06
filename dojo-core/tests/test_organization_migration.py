"""Real upgrades from the last single-workspace schema; never the developer DB."""

from alembic import command
from sqlalchemy import inspect, text

from tests.test_schema_init import config, database  # noqa: F401


def test_existing_ownership_and_credentials_survive_upgrade(database):  # noqa: F811
    url, engine = database
    command.upgrade(config(url), "0021_media_preview_jobs")
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO clients
            (id, name, kind, created_at, created_by, credential_hash)
            VALUES (12, 'Existing browser', 'browser', now(), 'cli', :hash)"""),
                           {"hash": "a" * 64})
        connection.execute(text("""INSERT INTO packages (id, folder_name, created_at, status)
            VALUES (14, '01-11-2026 19-00', now(), 'active')"""))
        connection.execute(text("""INSERT INTO settings (key, value, updated_at)
            VALUES ('branding.caption_template', '"original"', now())"""))
    command.upgrade(config(url), "head")
    with engine.connect() as connection:
        organization = connection.execute(text("SELECT * FROM organizations")).mappings().one()
        assert organization["name"] == "Kaizen Aikido Akademi"
        assert organization["email"] == "kaizenaikidoakademi@gmail.com"
        assert organization["phone"] is None
        assert organization["active"] is True
        assert connection.execute(text(
            "SELECT id, credential_hash, organization_id FROM clients"
        )).one() == (12, "a" * 64, organization["id"])
        assert connection.execute(text(
            "SELECT id, folder_name, organization_id FROM packages"
        )).one() == (14, "01-11-2026 19-00", organization["id"])
        assert connection.execute(text(
            "SELECT value, organization_id FROM settings WHERE key = 'branding.caption_template'"
        )).one() == ("original", organization["id"])


def test_fresh_install_creates_initial_organization_and_required_ownership(database):  # noqa: F811
    url, engine = database
    command.upgrade(config(url), "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM organizations")) == 1
    for table in ("clients", "pairing_codes", "packages", "settings", "audit_events", "jobs",
                  "uploads", "yayin_zamani", "yayin_incelemesi", "meta_connections",
                  "meta_oauth_attempts", "consent_acceptances", "live_resource_versions",
                  "live_change_events"):
        column = next(c for c in inspect(engine).get_columns(table)
                      if c["name"] == "organization_id")
        assert column["nullable"] is False
