from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dojo import DojoActivity, DojoMetaConnection, DojoPairing, DojoPublishing, DojoSetup
from fastapi import Depends, FastAPI

from backend.deps import (
    build_activity,
    build_meta,
    build_pairing,
    build_publishing,
    build_setup,
    get_current_client,
)
from backend.routes import activity as activity_router
from backend.routes import health, packages
from backend.routes import media as media_router
from backend.routes import meta as meta_router
from backend.routes import pairing as pairing_router
from backend.routes import settings as settings_router
from backend.routes import setup as setup_router
from backend.routes.pairing import IpThrottle


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not hasattr(app.state, "publishing"):
        app.state.publishing = build_publishing()
    if not hasattr(app.state, "pairing"):
        app.state.pairing = build_pairing()
    if not hasattr(app.state, "activity"):
        app.state.activity = build_activity()
    if not hasattr(app.state, "setup"):
        app.state.setup = build_setup()
    if not hasattr(app.state, "meta"):
        app.state.meta = build_meta()
    yield


def create_app(
    publishing: DojoPublishing | None = None,
    pairing: DojoPairing | None = None,
    activity: DojoActivity | None = None,
    setup: DojoSetup | None = None,
    meta: DojoMetaConnection | None = None,
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
    if activity is not None:
        app.state.activity = activity
    if setup is not None:
        app.state.setup = setup
    if meta is not None:
        app.state.meta = meta
    if cookie_secure is None:
        cookie_secure = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    app.state.cookie_secure = cookie_secure
    app.state.throttle = IpThrottle()
    app.include_router(health.router)
    app.include_router(packages.router, dependencies=[Depends(get_current_client)])
    app.include_router(pairing_router.router)
    app.include_router(activity_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(setup_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(media_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(settings_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(meta_router.router)
    return app


app = create_app()
