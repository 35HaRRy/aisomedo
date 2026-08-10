from __future__ import annotations

import os
from pathlib import Path

from dojo import Client, DojoPairing, DojoPublishing
from dojo.adapters.db import PostgresStore
from fastapi import HTTPException, Request, Response

DEFAULT_URL = "postgresql+psycopg://dojo:dojo@localhost:5433/dojo"
COOKIE_NAME = "dojo_session"
SESSION_MAX_AGE = 30 * 24 * 3600


def build_publishing() -> DojoPublishing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    media_root = Path(os.environ.get("MEDIA_ROOT", "media"))
    store = PostgresStore(url)
    store.create_all()
    return DojoPublishing(packages=store, audit=store, media_root=media_root)


def build_pairing() -> DojoPairing:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    store = PostgresStore(url)
    store.create_all()
    return DojoPairing(pairing=store, audit=store)


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
