from __future__ import annotations

import pytest

from backend import serve


def test_app_is_not_imported_at_module_import_time() -> None:
    """Importing the entry point must not build the app before logging.

    ``backend.main`` constructs the FastAPI app at import time and can log on
    that path, so the import has to happen after ``configure_logging``.
    """
    assert not hasattr(serve, "app")


def test_main_configures_logging_before_running_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(
        serve, "configure_logging", lambda *args, **kwargs: order.append("configure")
    )
    monkeypatch.setattr(
        serve.uvicorn, "run", lambda *args, **kwargs: order.append("run")
    )
    serve.main()
    assert order == ["configure", "run"]
