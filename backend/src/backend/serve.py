"""Backend process entry point.

Runs Uvicorn with logging already configured for JSON output:
``log_config=None`` stops Uvicorn from replacing root handlers with its own
colored formatters, which would otherwise downgrade the shared
secret-safe format installed by :mod:`dojo.observability`.
"""

from __future__ import annotations

import logging

import uvicorn
from dojo.observability import configure_logging

logger = logging.getLogger(__name__)

HOST = "0.0.0.0"
PORT = 8000


def main() -> None:
    configure_logging("backend")
    # Imported after configure_logging: backend.main builds the app at import
    # time, and any record it emits on that path must already be JSON.
    from backend.main import app

    logger.info("backend starting", extra={"event": "service.startup"})
    try:
        uvicorn.run(app, host=HOST, port=PORT, log_config=None)
    finally:
        logger.info("backend stopped", extra={"event": "service.shutdown"})


if __name__ == "__main__":
    main()
