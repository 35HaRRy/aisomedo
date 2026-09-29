"""Structured, secret-safe JSON process logs for backend and worker.

One JSON object per physical line on stdout, carrying ``timestamp`` (UTC ISO
8601), ``level``, ``service`` and a stable ``event`` literal plus a small
allowlist of operational identifiers. Everything else is dropped by
construction rather than filtered afterwards:

- the log message and its interpolated arguments are never serialized, so
  legacy ``logger.warning("token=%s", token)`` calls cannot leak credentials
  (suppressing the text is cheaper and more reliable than trying to recognize
  every possible secret);
- only ``extra`` keys on the allowlist below reach a record, so request
  headers/bodies and raw SQL parameters are dropped even when a caller passes
  them;
- unexpected exceptions contribute their class name and stack frames
  (file/function/line) only, never the exception text, local variables or
  source lines;
- access logs drop query strings, client addresses, and signed artifact paths
  collapse to a fixed route label.

Callers opt in to structure by passing an explicit ``event`` literal;
records without one fall back to the logger name so legacy call sites still
produce a searchable event.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from types import TracebackType
from typing import TextIO

#: Always-present fields.
BASE_FIELDS = ("timestamp", "level", "service", "event")

#: The only ``extra`` keys copied from a LogRecord. Values must be primitive
#: (str/int/float/bool); anything else is dropped.
ALLOWED_FIELDS = (
    "job_id",
    "alert_id",
    "status",
    "error_type",
    "duration_ms",
    "http_method",
    "http_status",
)

#: Uvicorn emits access records on this logger with a fixed argument tuple.
ACCESS_LOGGER = "uvicorn.access"
ACCESS_EVENT = "http.access"

#: Signed artifact URLs carry an unguessable token in the path.
SIGNED_PATH_PREFIX = "/pub/"
SIGNED_ROUTE_LABEL = "/pub/{token}"

#: Records longer than this are dropped whole: truncation could otherwise
#: leave a partial secret behind, which is worse than a missing field.
MAX_VALUE_CHARS = 256

_MANAGED_HANDLER_FLAG = "_dojo_json_handler"


def _safe_text(value: object) -> str | None:
    """A loggable string, or ``None`` when the value must not be emitted."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_VALUE_CHARS:
        return None
    # Single-line by construction: json.dumps escapes newlines anyway, but a
    # record must stay one physical line per event.
    if any(char in text for char in "\r\n\x00"):
        return None
    return text


def _safe_value(value: object) -> str | int | float | bool | None:
    """Allowlisted ``extra`` value: primitives only, never nested payloads."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    return _safe_text(value)


def _timestamp(created: float) -> str:
    moment = datetime.fromtimestamp(created, tz=UTC).isoformat(timespec="milliseconds")
    return moment.replace("+00:00", "Z")


def _stack_frames(tb: TracebackType | None) -> list[dict[str, object]]:
    """Frame file/function/line only — no source lines, no local variables."""
    frames: list[dict[str, object]] = []
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(
            {
                "file": code.co_filename,
                "function": code.co_name,
                "line": tb.tb_lineno,
            }
        )
        tb = tb.tb_next
    return frames


def _access_fields(record: logging.LogRecord) -> dict[str, object]:
    """Method/status/route from a Uvicorn-shaped access record.

    Uvicorn formats these with
    ``'%s - "%s %s HTTP/%s" %d'`` and arguments
    ``(client_addr, method, full_path, http_version, status_code)``. The client
    address and the query string are deliberately not read; a signed artifact
    path is replaced by a fixed label so the token never reaches the log.
    """
    args = record.args
    if not isinstance(args, tuple) or len(args) != 5:
        return {}
    _client, method, target, _version, status = args
    fields: dict[str, object] = {}
    safe_method = _safe_text(method)
    if safe_method is not None:
        fields["http_method"] = safe_method
    if isinstance(status, int) and not isinstance(status, bool):
        fields["http_status"] = status
    path = target.split("?", 1)[0] if isinstance(target, str) else ""
    if path.startswith(SIGNED_PATH_PREFIX):
        path = SIGNED_ROUTE_LABEL
    safe_path = _safe_text(path)
    if safe_path is not None:
        fields["path"] = safe_path
    return fields


class JsonFormatter(logging.Formatter):
    """Render one LogRecord as one JSON object with no unsafe content."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        explicit = _safe_text(getattr(record, "event", None))
        if explicit is not None:
            event = explicit
        elif record.name == ACCESS_LOGGER:
            event = ACCESS_EVENT
        else:
            event = record.name
        payload: dict[str, object] = {
            "timestamp": _timestamp(record.created),
            "level": record.levelname,
            "service": self._service,
            "event": event,
        }
        for key in ALLOWED_FIELDS:
            if key in record.__dict__:
                value = _safe_value(record.__dict__[key])
                if value is not None:
                    payload[key] = value
        if record.name == ACCESS_LOGGER:
            payload.update(_access_fields(record))
        if record.exc_info is not None:
            exc_type = record.exc_info[0]
            payload["error_type"] = exc_type.__name__ if exc_type else "Exception"
            frames = _stack_frames(record.exc_info[2])
            if frames:
                payload["stack"] = frames
        return json.dumps(payload, default=str)


def configure_logging(
    service: str, *, stream: TextIO | None = None, level: int = logging.INFO
) -> None:
    """Install the JSON formatter on root and Uvicorn loggers, idempotently.

    Uvicorn replaces root handlers when it applies its own log config, so the
    backend entry point runs Uvicorn with ``log_config=None`` and configures
    logging here instead. Calling this twice leaves exactly one handler, so a
    repeated call never duplicates records. Uvicorn's own logger handlers are
    removed and propagation enabled so server and access records use the same
    JSON shape as the rest of the process.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _MANAGED_HANDLER_FLAG, False):
            root.removeHandler(existing)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    setattr(handler, _MANAGED_HANDLER_FLAG, True)
    root.addHandler(handler)
    root.setLevel(level)
    for name in (ACCESS_LOGGER, "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        for own in list(logger.handlers):
            logger.removeHandler(own)
        logger.propagate = True
        logger.setLevel(level)
