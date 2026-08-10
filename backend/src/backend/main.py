from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dojo import DojoPairing, DojoPublishing
from fastapi import Depends, FastAPI

from backend.deps import build_pairing, build_publishing, get_current_client
from backend.routes import health, packages
from backend.routes import pairing as pairing_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not hasattr(app.state, "publishing"):
        app.state.publishing = build_publishing()
    if not hasattr(app.state, "pairing"):
        app.state.pairing = build_pairing()
    yield


def create_app(
    publishing: DojoPublishing | None = None,
    pairing: DojoPairing | None = None,
    cookie_secure: bool | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Dojo publishing API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if publishing is not None:
        app.state.publishing = publishing
    if pairing is not None:
        app.state.pairing = pairing
    if cookie_secure is None:
        cookie_secure = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    app.state.cookie_secure = cookie_secure
    app.include_router(health.router)
    app.include_router(packages.router, dependencies=[Depends(get_current_client)])
    app.include_router(pairing_router.router)
    return app


app = create_app()
