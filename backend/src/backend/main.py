from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dojo import DojoPublishing
from fastapi import FastAPI

from backend.deps import build_publishing
from backend.routes import health, packages


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not hasattr(app.state, "publishing"):
        app.state.publishing = build_publishing()
    yield


def create_app(publishing: DojoPublishing | None = None) -> FastAPI:
    app = FastAPI(title="Dojo Publishing API", version="0.1.0", lifespan=lifespan)
    if publishing is not None:
        app.state.publishing = publishing
    app.include_router(health.router)
    app.include_router(packages.router)
    return app


app = create_app()
