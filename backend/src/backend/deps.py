from __future__ import annotations

import os
from pathlib import Path

from dojo import Client, DojoActivity, DojoMetaConnection, DojoPairing, DojoPublishing, DojoSetup
from dojo.adapters.db import PostgresStore
from dojo.adapters.meta import FernetCipher, StubMetaOAuthProvider
from fastapi import HTTPException, Request, Response

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5434/dojo"
COOKIE_NAME = "dojo_session"
SESSION_MAX_AGE = 30 * 24 * 3600


def build_publishing() -> DojoPublishing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=media_root,
    )


def build_pairing() -> DojoPairing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoPairing(pairing=store, audit=store)


def build_activity() -> DojoActivity:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoActivity(audit=store, pairing=store)


def build_meta() -> DojoMetaConnection:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    key = os.environ.get("META_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("META_TOKEN_ENCRYPTION_KEY is required")
    cipher = FernetCipher(key)
    provider = StubMetaOAuthProvider()
    return DojoMetaConnection(
        store=store,
        provider=provider,
        cipher=cipher,
        audit=store,
        app_id=os.environ.get("META_APP_ID", "dev_app_id"),
        app_secret=os.environ.get("META_APP_SECRET", "dev_secret"),
        redirect_uri=os.environ.get("META_REDIRECT_URI", "http://localhost:8000/api/meta/oauth/callback"),
        graph_version=os.environ.get("META_GRAPH_VERSION", "v19.0"),
        allowed_return_uris=[u.strip() for u in os.environ.get("META_ALLOWED_RETURN_URIS", "").split(",") if u.strip()],
    )


def build_setup() -> DojoSetup:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoSetup(setup=store, audit=store, pairing=store)


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
