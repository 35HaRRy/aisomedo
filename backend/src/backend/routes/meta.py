from __future__ import annotations

from typing import Any

from dojo import Client
from dojo.exceptions import (
    MetaAccountInvalid,
    MetaOAuthFailed,
    MetaOAuthStateInvalid,
    MetaProviderUnavailable,
    MetaReturnUriInvalid,
    MetaTokenInvalid,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.deps import get_current_client


def get_meta(request: Request) -> object:
    return request.app.state.meta


class StartIn(BaseModel):
    return_uri: str | None = None


class StartOut(BaseModel):
    auth_url: str
    attempt_id: str


class AttemptOut(BaseModel):
    id: str
    status: str
    candidates: list[dict]


class StatusOut(BaseModel):
    health: str
    connection_type: str = "facebook_login"
    ig_user_id: str | None = None
    ig_username: str | None = None
    page_id: str | None = None
    page_name: str | None = None
    expires_at: str | None = None
    last_checked_at: str | None = None
    last_refreshed_at: str | None = None
    last_error: str | None = None


class SelectIn(BaseModel):
    ig_user_id: str


router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.post("/instagram/token", response_model=StatusOut)
def connect_instagram_token(
    body: Any = Body(default=None),
    client: Client = Depends(get_current_client),
    meta: Any = Depends(get_meta),
) -> StatusOut:
    # Validate here so validation errors cannot echo the submitted secret as `input`.
    token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token.strip() or len(token) > 16384:
        raise HTTPException(status_code=422, detail="A valid Instagram access_token is required")
    try:
        status = meta.connect_instagram_token(client.id, token)
    except MetaTokenInvalid:
        raise HTTPException(
            status_code=422, detail="Instagram token invalid or required permissions missing"
        ) from None
    except MetaProviderUnavailable:
        raise HTTPException(
            status_code=502, detail="Instagram verification unavailable; retry later"
        ) from None
    return StatusOut(**status.to_dict())


@router.post("/oauth/start", response_model=StartOut)
def oauth_start(
    body: StartIn,
    client: Client = Depends(get_current_client),
    meta: Any = Depends(get_meta),
) -> StartOut:
    try:
        auth_url, attempt_id = meta.start(client.id, body.return_uri)  # type: ignore[attr-defined]
    except MetaReturnUriInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StartOut(auth_url=auth_url, attempt_id=attempt_id)


@router.get("/oauth/callback")
def oauth_callback(
    state: str,
    code: str,
    request: Request,
) -> object:
    meta = request.app.state.meta  # type: ignore[attr-defined]
    try:
        attempt_id = meta.complete_callback(state, code)  # type: ignore[attr-defined]
    except MetaOAuthStateInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MetaOAuthFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # check if attempt has return_uri to redirect
    try:
        rec = meta._store.get_meta_attempt(attempt_id)  # type: ignore[attr-defined]
        return_uri = rec.get("return_uri") if rec else None
        if return_uri:
            sep = "&" if "?" in return_uri else "?"
            return RedirectResponse(url=f"{return_uri}{sep}attempt_id={attempt_id}", status_code=302)
    except Exception:
        pass
    return {"attempt_id": attempt_id}


@router.get("/oauth/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(
    attempt_id: str,
    client: Client = Depends(get_current_client),
    meta: Any = Depends(get_meta),
) -> AttemptOut:
    try:
        attempt = meta.get_attempt(client.id, attempt_id)  # type: ignore[attr-defined]
    except MetaOAuthStateInvalid as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AttemptOut(id=attempt.id, status=attempt.status, candidates=[c.to_dict() for c in attempt.candidates])


@router.post("/oauth/attempts/{attempt_id}/select", response_model=StatusOut)
def select_account(
    attempt_id: str,
    body: SelectIn,
    client: Client = Depends(get_current_client),
    meta: Any = Depends(get_meta),
) -> StatusOut:
    try:
        status = meta.select_account(client.id, attempt_id, body.ig_user_id)  # type: ignore[attr-defined]
    except MetaOAuthStateInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MetaAccountInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaOAuthFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StatusOut(
        health=status.health,
        connection_type=status.connection_type,
        ig_user_id=status.ig_user_id,
        ig_username=status.ig_username,
        page_id=status.page_id,
        page_name=status.page_name,
        expires_at=status.expires_at.isoformat() if status.expires_at else None,
        last_checked_at=status.last_checked_at.isoformat() if status.last_checked_at else None,
        last_refreshed_at=status.last_refreshed_at.isoformat() if status.last_refreshed_at else None,
        last_error=status.last_error,
    )


@router.get("/status", response_model=StatusOut)
def get_status(
    _client: Client = Depends(get_current_client),
    meta: Any = Depends(get_meta),
) -> StatusOut:
    status = meta.get_status()  # type: ignore[attr-defined]
    return StatusOut(
        health=status.health,
        connection_type=status.connection_type,
        ig_user_id=status.ig_user_id,
        ig_username=status.ig_username,
        page_id=status.page_id,
        page_name=status.page_name,
        expires_at=status.expires_at.isoformat() if status.expires_at else None,
        last_checked_at=status.last_checked_at.isoformat() if status.last_checked_at else None,
        last_refreshed_at=status.last_refreshed_at.isoformat() if status.last_refreshed_at else None,
        last_error=status.last_error,
    )
