"""Explicit, serialized database initialization: ``python -m dojo.schema``."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from dojo.schema_checks import preflight_emission_conflicts, validate_legacy_schema

SCHEMA_INITIALIZATION_LOCK_KEY = 0x444F4A4F5343484D
LEGACY_BASELINE = "0013_instagram_login"
EMISSION_REVISION = "0014_emission_idempotency"


def migration_config() -> Config:
    """Resolve migrations in installed wheels or the editable source checkout."""
    scripts = Path(__file__).resolve().parent / "migrations"
    if not scripts.is_dir():
        scripts = Path(__file__).resolve().parents[2] / "migrations"
    config = Config()
    config.set_main_option("script_location", str(scripts))
    config.set_main_option("path_separator", "os")
    return config


def initialize_database(url: str | None = None) -> None:
    """Upgrade fresh/versioned DBs; validate unversioned create_all before stamp.

    Lock, preflight, optional stamp and migrations share one transaction. On any
    failure every schema/version change rolls back. Run before app processes start.
    """
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for schema initialization")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                               {"key": SCHEMA_INITIALIZATION_LOCK_KEY})
            config = migration_config()
            config.attributes["connection"] = connection
            tables = set(inspect(connection).get_table_names())
            versioned = "alembic_version" in tables and connection.scalar(
                text("SELECT count(*) FROM alembic_version")
            )
            if not versioned and tables - {"alembic_version"}:
                preflight_emission_conflicts(connection)
                at_head = validate_legacy_schema(connection)
                command.stamp(config, EMISSION_REVISION if at_head else LEGACY_BASELINE)
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def main() -> None:
    initialize_database()
    print("Database schema is at head.")


if __name__ == "__main__":
    main()
