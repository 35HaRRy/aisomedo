from __future__ import annotations

import io
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from dojo.observability import (
    ACCESS_EVENT,
    ALLOWED_FIELDS,
    BASE_FIELDS,
    DERIVED_FIELDS,
    SIGNED_ROUTE_LABEL,
    UNKNOWN_EVENT,
    JsonFormatter,
    configure_logging,
)

SECRETS = (
    "s3cr3t-bearer-token",
    "AAAA1111:bbbb2222:cccc3333",
    "oauth-code-abcdef",
    "hmac-signed-url-signature",
)

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")


@contextmanager
def _capture(
    name: str = "worker.main", service: str = "worker"
) -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """A logger whose only handler writes JSON to a private stream.

    The logger under test is a real process-wide singleton, so its handlers,
    level and propagate flag are restored on exit. Without this, a formatter
    test silently reconfigures logging for every later test module: the old
    helper left ``worker.main``, ``dojo.publishing`` and ``uvicorn.access``
    pinned at DEBUG with propagation off for the rest of the session.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(service))
    logger = logging.getLogger(name)
    saved = _state(logger)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    try:
        yield logger, stream
    finally:
        logger.handlers[:] = saved[0]
        logger.setLevel(saved[1])
        logger.propagate = saved[2]


def _records(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def _access(logger: logging.Logger, target: str, status: int = 200) -> None:
    """Emit exactly what uvicorn.access emits for one request."""
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "10.0.0.1",
        "GET",
        target,
        "1.1",
        status,
    )


def _state(logger: logging.Logger) -> tuple[list[logging.Handler], int, bool]:
    return (logger.handlers[:], logger.level, logger.propagate)


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Undo configure_logging's process-wide handler changes."""
    watched = (*_UVICORN_LOGGERS, "")
    saved = {name: _state(logging.getLogger(name)) for name in watched}
    yield
    for name in watched:
        logger = logging.getLogger(name)
        handlers, level, propagate = saved[name]
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def test_explicit_event_and_allowlisted_ids() -> None:
    with _capture(service="backend") as (logger, stream):
        logger.warning(
            "publication failed",
            extra={
                "event": "job.outcome",
                "job_id": "job-1",
                "alert_id": "alert-9",
                "status": "failed",
                "error_type": "RenderFailed",
                "duration_ms": 1234.5,
            },
        )
    (record,) = _records(stream)
    assert record["service"] == "backend"
    assert record["level"] == "WARNING"
    assert record["event"] == "job.outcome"
    assert record["job_id"] == "job-1"
    assert record["alert_id"] == "alert-9"
    assert record["status"] == "failed"
    assert record["error_type"] == "RenderFailed"
    assert record["duration_ms"] == 1234.5


def test_timestamp_is_utc_iso8601() -> None:
    with _capture() as (logger, stream):
        logger.info("hello", extra={"event": "service.startup"})
    stamp = _records(stream)[0]["timestamp"]
    assert stamp.endswith("Z")
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo == UTC
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 60


def test_legacy_record_falls_back_to_logger_name() -> None:
    with _capture(name="dojo.publishing") as (logger, stream):
        logger.info("plain legacy call")
    (record,) = _records(stream)
    assert record["event"] == "dojo.publishing"


def test_message_text_is_never_serialized() -> None:
    with _capture() as (logger, stream):
        logger.warning("nothing to see here")
    (record,) = _records(stream)
    assert "message" not in record
    assert "nothing to see here" not in stream.getvalue()


@pytest.mark.parametrize(
    ("event", "forbidden"),
    [
        ("s3cr3t-bearer-token", "s3cr3t-bearer-token"),
        ("token=AAAA1111:bbbb2222:cccc3333", "AAAA1111:bbbb2222:cccc3333"),
        ("oauth code abcdef", "abcdef"),
        ("Job.Outcome", "Job.Outcome"),
        ("job outcome", "job outcome"),
        ("job.outcome/", "job.outcome/"),
        ("../etc/passwd", "passwd"),
        ("job.outcome?admin=1", "admin=1"),
        ("job.outcome\nsecond line", "second line"),
        ("job.{}", "job.{}"),
        ("job.outcome;drop", "drop"),
    ],
)
def test_secret_in_event_cannot_reach_output(event: str, forbidden: str) -> None:
    """A rejected event falls back to the logger name, never to the text."""
    with _capture() as (logger, stream):
        logger.warning("payload", extra={"event": event})
    raw = stream.getvalue()
    assert event not in raw
    assert forbidden not in raw
    assert raw.count("\n") == 1
    (record,) = _records(stream)
    assert record["event"] == "worker.main"


def test_valid_event_literals_are_preserved() -> None:
    for event in ("job.outcome", "service.startup", "http.access", "a", "a_b.c_d"):
        with _capture() as (logger, stream):
            logger.warning("payload", extra={"event": event})
        assert _records(stream)[0]["event"] == event


def test_event_fallback_for_unusable_logger_name() -> None:
    """A logger name that is not a safe literal falls back to the constant."""
    with _capture(name="weird logger name!") as (logger, stream):
        logger.warning("payload")
    assert _records(stream)[0]["event"] == UNKNOWN_EVENT


@pytest.mark.parametrize(
    "case",
    [
        "message_args",
        "exception_text",
        "access_query",
        "access_signed_path",
        "nested_extra",
        "multiline_args",
        "event_field",
        "sql_params",
    ],
)
def test_secrets_never_reach_the_output(case: str) -> None:
    name = "uvicorn.access" if case.startswith("access") else "worker.main"
    with _capture(name=name) as (logger, stream):
        for secret in SECRETS:
            if case == "message_args":
                logger.warning("token=%s rejected", secret)
            elif case == "exception_text":
                try:
                    raise RuntimeError(f"upstream rejected {secret}")
                except RuntimeError:
                    logger.exception(
                        "unexpected failure", extra={"event": "worker.tick_failed"}
                    )
            elif case == "access_query":
                _access(logger, f"/api/packages/active?access_token={secret}")
            elif case == "access_signed_path":
                _access(logger, f"/pub/{secret}")
            elif case == "nested_extra":
                logger.warning(
                    "nested",
                    extra={"event": "job.outcome", "context": {"device_token": secret}},
                )
            elif case == "multiline_args":
                logger.warning("first %s\nsecond %s", secret, "tail\n" + secret)
            elif case == "event_field":
                logger.warning("leak", extra={"event": f"job.outcome.{secret}"})
            else:
                logger.warning("query", extra={"event": "job.outcome", "params": (secret,)})
    raw = stream.getvalue()
    for line in raw.splitlines():
        json.loads(line)  # one JSON object per physical line
    for secret in SECRETS:
        assert secret not in raw
        assert quote(secret, safe="") not in raw
    for record in _records(stream):
        assert set(record) <= set(BASE_FIELDS) | set(ALLOWED_FIELDS) | set(DERIVED_FIELDS)


def test_only_allowlisted_extras_are_serialized() -> None:
    with _capture() as (logger, stream):
        logger.warning(
            "nope",
            extra={
                "event": "job.outcome",
                "job_id": "job-2",
                "authorization": "Bearer abc",
                "request": {"headers": {"Cookie": "sid=1"}},
            },
        )
    (record,) = _records(stream)
    assert record["job_id"] == "job-2"
    assert "authorization" not in record
    assert "request" not in record


def test_derived_fields_are_never_read_from_extra() -> None:
    """``path``/``stack`` are formatter-derived; a caller cannot inject them."""
    with _capture() as (logger, stream):
        logger.warning(
            "spoof",
            extra={"event": "job.outcome", "path": "/pub/s3cr3t", "stack": ["x"]},
        )
    (record,) = _records(stream)
    assert "path" not in record
    assert "stack" not in record


def test_access_record_keeps_method_status_and_drops_query() -> None:
    with _capture(name="uvicorn.access", service="backend") as (logger, stream):
        _access(logger, "/api/packages/active?state=abc&token=xyz", status=503)
    (record,) = _records(stream)
    assert record["event"] == ACCESS_EVENT
    assert record["service"] == "backend"
    assert record["http_method"] == "GET"
    assert record["http_status"] == 503
    assert record["path"] == "/api/packages/active"
    assert "state=abc" not in stream.getvalue()
    assert "10.0.0.1" not in stream.getvalue()


@pytest.mark.parametrize(
    "target",
    [
        "/pub/deadbeef?expires=1",
        "/pub/deadbeef",
        "/pub/deadbeef/",
        "/pub/deadbeef/extra-segment",
        "/api/pub/deadbeef",  # ASGI mount / root_path prefix
        "/pub/AAAA1111:bbbb2222:cccc3333?sig=deadbeef",
        "/pub/deadbeef%20encoded",
    ],
)
def test_signed_artifact_path_becomes_a_fixed_label(target: str) -> None:
    """Route-aware collapsing: every signed-route variant gets the label."""
    with _capture(name="uvicorn.access") as (logger, stream):
        _access(logger, target, status=404)
    (record,) = _records(stream)
    assert record["path"] == SIGNED_ROUTE_LABEL
    assert "deadbeef" not in stream.getvalue()


@pytest.mark.parametrize(
    "target",
    [
        "/api/packages/active",
        "/health",
        "/pubx/deadbeef",
        "/public/deadbeef",
        "/api/packages/active/publication",
    ],
)
def test_non_signed_routes_keep_their_real_path(target: str) -> None:
    """Only the signed-artifact route is collapsed; other routes stay legible."""
    with _capture(name="uvicorn.access") as (logger, stream):
        _access(logger, target)
    (record,) = _records(stream)
    assert record["path"] == target


def test_unexpected_exception_keeps_class_and_frames_only() -> None:
    with _capture() as (logger, stream):
        try:
            raise RuntimeError("token=s3cr3t-bearer-token")
        except RuntimeError:
            logger.exception("tick failed", extra={"event": "worker.tick_failed"})
    (record,) = _records(stream)
    assert record["error_type"] == "RuntimeError"
    assert record["event"] == "worker.tick_failed"
    assert "s3cr3t-bearer-token" not in stream.getvalue()
    # no source line, no local variables
    assert 'raise RuntimeError("token=' not in stream.getvalue()
    (frame,) = record["stack"]
    assert set(frame) == {"file", "function", "line"}
    assert frame["function"] == "test_unexpected_exception_keeps_class_and_frames_only"
    assert frame["file"].endswith("test_observability.py")
    assert frame["line"] > 0


def test_configure_logging_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, restore_logging: None
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    configure_logging("backend")
    configure_logging("backend")
    logging.getLogger("backend.serve").info("up", extra={"event": "service.startup"})
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert json.loads(lines[0])["service"] == "backend"


def test_configure_logging_keeps_uvicorn_records(
    monkeypatch: pytest.MonkeyPatch, restore_logging: None
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    configure_logging("backend")
    access = logging.getLogger("uvicorn.access")
    assert access.propagate is True
    assert access.handlers == []
    _access(access, "/health?x=1")
    (record,) = _records(stream)
    assert record["event"] == ACCESS_EVENT
    assert record["path"] == "/health"
    assert record["http_status"] == 200


def test_multiline_message_stays_one_line() -> None:
    with _capture() as (logger, stream):
        logger.warning("line one\nline two\nline three")
    raw = stream.getvalue()
    assert raw.count("\n") == 1
    assert json.loads(raw)["event"] == "worker.main"


def test_repeated_events_produce_one_line_each() -> None:
    with _capture() as (logger, stream):
        for index in range(3):
            logger.info("tick", extra={"event": "job.outcome", "job_id": f"job-{index}"})
    raw = stream.getvalue()
    assert raw.count("\n") == 3
    assert [r["job_id"] for r in _records(stream)] == ["job-0", "job-1", "job-2"]


def test_capture_restores_every_logger_it_touches() -> None:
    """A capture must not leave process-wide logging reconfigured."""
    names = ("worker.main", "dojo.publishing", "uvicorn.access")
    before = {name: _state(logging.getLogger(name)) for name in names}
    root_before = _state(logging.getLogger())
    for name in names:
        with _capture(name=name):
            logging.getLogger(name).warning("inside")
    for name in names:
        after = _state(logging.getLogger(name))
        assert after == before[name], f"{name} was left reconfigured"
    assert _state(logging.getLogger()) == root_before
