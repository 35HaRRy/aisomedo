from __future__ import annotations

from collections.abc import Iterator

import pytest
from dojo.adapters.db import PostgresStore
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def _pg_session() -> Iterator[PostgresStore]:
    """One real PostgreSQL container shared by all tests in the session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql+psycopg://")
        store = PostgresStore(url)
        store.create_all()
        try:
            yield store
        finally:
            store.dispose()


@pytest.fixture
def pg_store(_pg_session: PostgresStore) -> Iterator[PostgresStore]:
    """Truncate both tables before each DB test so the shared container stays isolated.

    Only tests that request ``pg_store`` touch PostgreSQL; unit tests and the
    FFmpeg harness never start a container.
    """
    store = _pg_session
    with store._engine.begin() as conn:  # noqa: SLF001
        conn.execute(
            text("TRUNCATE TABLE push_registrations, consent_acceptances, consent_policies, pairing_codes, "
                 "clients, audit_events, packages, uploads, jobs, settings, yayin_zamani, "
                 "yayin_incelemesi RESTART IDENTITY CASCADE")
        )
    yield store
