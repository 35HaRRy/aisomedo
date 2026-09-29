from __future__ import annotations

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

#: Only libpq dialects accept ``connect_timeout`` and ``options``. Anything
#: else would construct fine, then fail every probe silently, so reject it at
#: startup instead.
_POSTGRES_SCHEMES = ("postgresql", "postgres")


class DatabaseReadiness:
    """Bounded database connectivity probe for ``/ready``.

    Owns a dedicated small engine: 0.5s pool timeout, 2s connect timeout
    and 1s statement timeout. Worst case stays below the 5s container
    probe timeout. Read-only ``SELECT 1``; never writes schema.
    """

    POOL_TIMEOUT = 0.5
    CONNECT_TIMEOUT = 2
    STATEMENT_TIMEOUT_MS = 1000

    def __init__(self, url: str) -> None:
        # "postgresql+psycopg" -> "postgresql": the dialect decides whether
        # connect_timeout/options are meaningful. Name the dialect only; the
        # DSN carries credentials.
        dialect = url.split(":", 1)[0].split("+", 1)[0]
        if dialect not in _POSTGRES_SCHEMES:
            raise ValueError(
                f"readiness probe requires a postgresql DATABASE_URL scheme; got {dialect!r}"
            )
        self.pool_timeout = self.POOL_TIMEOUT
        self.connect_args = {
            "connect_timeout": self.CONNECT_TIMEOUT,
            "options": f"-c statement_timeout={self.STATEMENT_TIMEOUT_MS}",
        }
        self._failing = False
        self._engine: Engine = create_engine(
            url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=self.pool_timeout,
            connect_args=self.connect_args,
        )

    def check(self) -> bool:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - any failure means not ready
            if not self._failing:
                # Exception type only: driver messages can echo the DSN.
                logger.warning("readiness probe failed: %s", type(exc).__name__)
            self._failing = True
            return False
        self._failing = False
        return True

    def close(self) -> None:
        self._engine.dispose()
