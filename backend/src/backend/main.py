from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from dojo import DojoActivity, DojoMetaConnection, DojoPairing, DojoPublishing, DojoSetup
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.deps import (
    build_activity,
    build_meta,
    build_pairing,
    build_publishing,
    build_setup,
    get_current_client,
)
from backend.proxy import ProxyHeadersMiddleware, parse_trusted_proxies
from backend.routes import activity as activity_router
from backend.routes import compat as compat_router
from backend.routes import health, packages
from backend.routes import media as media_router
from backend.routes import meta as meta_router
from backend.routes import pairing as pairing_router
from backend.routes import publication as publication_router
from backend.routes import reviews as reviews_router
from backend.routes import settings as settings_router
from backend.routes import setup as setup_router
from backend.routes.pairing import IpThrottle
from backend.versions import VersionPolicy, resolve_version_policy


class ClientVersionMiddleware:
    """Block outdated Android device clients with an update prompt (#24).

    Only ``Authorization: Bearer`` device requests under ``/api/*`` are
    gated; browser session-cookie traffic is never blocked. ``/api/compat``,
    ``/health``, ``/ready`` and Meta OAuth callbacks stay reachable so an
    outdated client can always discover the update URL.
    """

    EXEMPT_PREFIXES = ("/health", "/ready", "/api/compat", "/api/meta/oauth/")

    def __init__(self, app: ASGIApp, policy: VersionPolicy) -> None:
        self.app = app
        self._policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/api/") and not path.startswith(self.EXEMPT_PREFIXES):
                headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                authorization = headers.get("authorization", "")
                if authorization.lower().startswith("bearer "):
                    try:
                        version = int(headers.get("x-android-version-code", "").strip())
                    except ValueError:
                        version = 0
                    if version < self._policy.min_version_code:
                        response = JSONResponse(
                            status_code=426,
                            content={
                                "detail": "update_required",
                                "update_url": self._policy.update_url,
                            },
                        )
                        await response(scope, receive, send)
                        return
        await self.app(scope, receive, send)


def _wire_setup_meta(app: FastAPI) -> None:
    setup = getattr(app.state, "setup", None)
    meta = getattr(app.state, "meta", None)
    if setup is not None and meta is not None and getattr(setup, "_meta", None) is None:
        setup.attach_meta(meta)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    readiness_probe = None
    if getattr(app.state, "readiness", None) is None:
        from backend.deps import DEFAULT_URL
        from backend.readiness import DatabaseReadiness

        url = os.environ.get("DATABASE_URL", DEFAULT_URL)
        readiness_probe = DatabaseReadiness(url)
        app.state.readiness = readiness_probe.check
    if not hasattr(app.state, "publishing"):
        app.state.publishing = build_publishing()
    try:
        app.state.publishing.repair_open_folders(requester="system")
    except Exception:  # noqa: BLE001 - startup repair never blocks boot
        import logging

        logging.getLogger(__name__).exception(
            "open-folder repair failed",
            extra={"event": "startup.folder_repair_failed", "status": "error"},
        )
    if not hasattr(app.state, "pairing"):
        app.state.pairing = build_pairing()
    if not hasattr(app.state, "activity"):
        app.state.activity = build_activity()
    if not hasattr(app.state, "meta"):
        try:
            app.state.meta = build_meta()
        except Exception as exc:  # noqa: BLE001 - meta optional (e.g. missing key)
            import logging

            logging.getLogger(__name__).warning(
                "meta connection not configured: %s",
                exc,
                extra={"event": "startup.meta_unavailable"},
            )
            app.state.meta = None
    if not hasattr(app.state, "setup"):
        app.state.setup = build_setup(meta=getattr(app.state, "meta", None))
    else:
        _wire_setup_meta(app)
    _wire_setup_meta(app)
    try:
        yield
    finally:
        if readiness_probe is not None:
            readiness_probe.close()


def create_app(
    publishing: DojoPublishing | None = None,
    pairing: DojoPairing | None = None,
    activity: DojoActivity | None = None,
    setup: DojoSetup | None = None,
    meta: DojoMetaConnection | None = None,
    cookie_secure: bool | None = None,
    trusted_proxies: str | None = None,
    readiness: Callable[[], bool] | None = None,
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
    if readiness is not None:
        app.state.readiness = readiness
    _wire_setup_meta(app)
    if trusted_proxies is None:
        trusted_proxies = os.environ.get("TRUSTED_PROXIES", "private_ranges")
    try:
        parse_trusted_proxies(trusted_proxies)
    except ValueError as exc:
        raise ValueError(f"invalid TRUSTED_PROXIES {trusted_proxies!r}: {exc}") from exc
    app.add_middleware(ProxyHeadersMiddleware, trusted_proxies=trusted_proxies)
    if cookie_secure is None:
        cookie_secure = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    app.state.cookie_secure = cookie_secure
    from backend.deps import resolve_public_base_url as _resolve_origin

    _resolve_origin(cookie_secure)
    app.state.throttle = IpThrottle()
    app.state.version_policy = resolve_version_policy()
    app.add_middleware(ClientVersionMiddleware, policy=app.state.version_policy)
    app.include_router(health.router)
    app.include_router(compat_router.router)
    app.include_router(packages.router, dependencies=[Depends(get_current_client)])
    app.include_router(pairing_router.router)
    app.include_router(activity_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(setup_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(media_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(settings_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(meta_router.router)
    app.include_router(publication_router.router, dependencies=[Depends(get_current_client)])
    app.include_router(publication_router.fetch_router)
    app.include_router(reviews_router.router, dependencies=[Depends(get_current_client)])
    return app


app = create_app()
