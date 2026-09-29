from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


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
        self.pool_timeout = self.POOL_TIMEOUT
        self.connect_args = {
            "connect_timeout": self.CONNECT_TIMEOUT,
            "options": f"-c statement_timeout={self.STATEMENT_TIMEOUT_MS}",
        }
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
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._engine.dispose()
