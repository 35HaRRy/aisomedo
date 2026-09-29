from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dojo import Client, DojoActivity, DojoMetaConnection, DojoPairing, DojoPublishing, DojoSetup
from dojo.adapters.db import PostgresStore
from dojo.adapters.meta import FernetCipher, HttpInstagramTokenProvider, StubMetaOAuthProvider
from fastapi import HTTPException, Request, Response

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5434/dojo"
COOKIE_NAME = "dojo_session"
SESSION_MAX_AGE = 30 * 24 * 3600


def resolve_cookie_secure(explicit: bool | None = None) -> bool:
    """COOKIE_SECURE contract: default true; only explicit false disables."""
    if explicit is not None:
        return explicit
    return os.environ.get("COOKIE_SECURE", "true").lower() == "true"


def resolve_public_base_url(cookie_secure: bool | None = None) -> str:
    """Canonical public origin for browser/OAuth/signed URLs.

    ``PUBLIC_HTTPS_ORIGIN`` wins when set (prod contract: https); falls back
    to ``PUBLIC_BASE_URL``; localhost default is dev-only. Frontend stays
    same-origin and never consumes this.

    Fail-closed on operator typo: an explicitly configured non-https origin
    (or any non-localhost http origin) raises while COOKIE_SECURE resolves
    true. Dev ``localhost`` default stays unaffected.
    """
    raw_origin = os.environ.get("PUBLIC_HTTPS_ORIGIN", "").strip()
    origin = raw_origin or os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").strip()
    origin = origin.rstrip("/") or "http://localhost:8000"
    if resolve_cookie_secure(cookie_secure):
        host = (urlparse(origin).hostname or "").lower()
        if urlparse(origin).scheme != "https" and host not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError(
                f"refusing non-https public origin {origin!r} while COOKIE_SECURE is true; "
                "fix PUBLIC_HTTPS_ORIGIN to an https:// URL (dev localhost exempt)"
            )
    return origin


def _maybe_create_all(store: PostgresStore) -> None:
    """Create schema unless SKIP_CREATE_ALL=1 (initializer owns prod schema).

    Same contract as the worker: only the literal string "1" skips; unset or
    any other value keeps dev behavior.
    """
    if os.environ.get("SKIP_CREATE_ALL") == "1":
        return
    store.create_all()


def build_publishing() -> DojoPublishing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    _maybe_create_all(store)
    kwargs: dict = {}
    try:
        from dojo.adapters.meta import FernetCipher, HttpMetaPublisher

        key = os.environ.get("META_TOKEN_ENCRYPTION_KEY", "")
        if key:
            kwargs["meta"] = HttpMetaPublisher(
                connection_store=store,
                cipher=FernetCipher(key),
                graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
            )
    except Exception:  # noqa: BLE001 - publishing works with stub in dev
        pass
    secret = os.environ.get("SIGNED_URL_SECRET", "")
    base_url = resolve_public_base_url() if secret else ""
    try:
        from dojo.adapters.signed_urls import HmacSignedUrlStore

        if secret:
            # base_url resolved OUTSIDE the try: a misconfigured public
            # origin must raise, not silently fall back to the stub.
            # Stub fallback applies only when no secret is configured.
            kwargs["signed_urls"] = HmacSignedUrlStore(
                base_url=base_url,
                secret=secret,
            )
    except Exception:  # noqa: BLE001
        pass
    return DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=media_root,
        **kwargs,
    )


def build_pairing() -> DojoPairing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    _maybe_create_all(store)
    return DojoPairing(pairing=store, audit=store)


def build_activity() -> DojoActivity:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    _maybe_create_all(store)
    return DojoActivity(audit=store, pairing=store)


def build_meta() -> DojoMetaConnection:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    _maybe_create_all(store)
    key = os.environ.get("META_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("META_TOKEN_ENCRYPTION_KEY is required")
    cipher = FernetCipher(key)
    provider = StubMetaOAuthProvider()
    return DojoMetaConnection(
        store=store,
        provider=provider,
        instagram_provider=HttpInstagramTokenProvider(
            graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
        ),
        cipher=cipher,
        audit=store,
        app_id=os.environ.get("META_APP_ID", "dev_app_id"),
        app_secret=os.environ.get("META_APP_SECRET", "dev_secret"),
        redirect_uri=os.environ.get("META_REDIRECT_URI", "").strip()
        or f"{resolve_public_base_url()}/api/meta/oauth/callback",
        graph_version=os.environ.get("META_GRAPH_VERSION", "v26.0"),
        allowed_return_uris=[u.strip() for u in os.environ.get("META_ALLOWED_RETURN_URIS", "").split(",") if u.strip()],
    )


def build_setup(meta: DojoMetaConnection | None = None) -> DojoSetup:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    _maybe_create_all(store)
    return DojoSetup(setup=store, audit=store, pairing=store, meta=meta)


def get_current_client(request: Request, response: Response) -> Client:
    pairing: DojoPairing = request.app.state.pairing
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        client = pairing.authenticate_bearer(authorization[7:].strip())
        if client is not None:
            return client
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        client = pairing.authenticate_session(session_id)
        if client is not None:
            response.set_cookie(
                COOKIE_NAME,
                session_id,
                httponly=True,
                secure=request.app.state.cookie_secure,
                samesite="lax",
                path="/",
                max_age=SESSION_MAX_AGE,
            )
            return client
    raise HTTPException(status_code=401, detail="unauthorized")
