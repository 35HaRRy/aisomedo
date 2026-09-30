from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dojo.adapters.db import Base
from sqlalchemy import engine_from_config, pool

config = context.config
if url := os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
if config.config_file_name is not None:
    # Alembic's ini names only root/sqlalchemy/alembic. The default
    # disable_existing_loggers=True would therefore silence every application
    # logger in the process running an in-process migration, which is how a
    # migration run would silently mute delivery and health logging.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata, literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if connection := config.attributes.get("connection"):
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
