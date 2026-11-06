from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Literal

from dojo import (
    BrandingAssetNotFound,
    BrandingAssets,
    Client,
    ClientNotFound,
    DojoPairing,
    DojoPublishing,
    PairingError,
    PushTokenInvalid,
)
from dojo.pairing import CODE_TTL
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from backend.deps import COOKIE_NAME, SESSION_MAX_AGE, get_current_client
from backend.organizations import get_organization_services, services_for_organization
from backend.snapshots import versioned_snapshot

TTL_SECONDS = int(CODE_TTL.total_seconds())


def get_pairing(request: Request) -> DojoPairing:
    return request.app.state.pairing


class IpThrottle:
    def __init__(self, *, limit: int = 10, window: float = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._attempts.setdefault(ip, deque())
            while window and now - window[0] > self._window:
                window.popleft()
            if len(window) >= self._limit:
                return False
            window.append(now)
            return True


def get_throttle(request: Request) -> IpThrottle:
    return request.app.state.throttle


def enforce_throttle(request: Request, throttle: IpThrottle = Depends(get_throttle)) -> None:
    ip = request.client.host if request.client is not None else "unknown"
    if not throttle.allow(ip):
        raise HTTPException(status_code=429, detail="too many attempts")


router = APIRouter(prefix="/api/pairing", tags=["pairing"])


class CodeOut(BaseModel):
    code: str
    expires_at: datetime
    ttl_seconds: int


class ValidateIn(BaseModel):
    code: str
    kind: Literal["device", "browser"]
    name: str


class ClientOut(BaseModel):
    id: int
    organization_id: int
    name: str
    kind: str
    created_at: datetime
    created_by: str
    last_seen_at: datetime | None
    revoked_at: datetime | None


class PairingOut(BaseModel):
    client_id: int
    kind: Literal["device", "browser"]
    token: str | None = None


@router.post("/codes", response_model=CodeOut)
def create_code(
    requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> CodeOut:
    issued = pairing.create_pairing_code(requester=str(requester.id),
                                         organization_id=requester.organization_id)
    return CodeOut(code=issued.raw_code, expires_at=issued.expires_at, ttl_seconds=TTL_SECONDS)


@router.post("/validate", response_model=PairingOut, dependencies=[Depends(enforce_throttle)])
def validate(
    body: ValidateIn, request: Request, pairing: DojoPairing = Depends(get_pairing)
) -> Response:
    try:
        result = pairing.validate_code(code=body.code, kind=body.kind, name=body.name)
    except PairingError as exc:
        raise HTTPException(status_code=401, detail="invalid pairing code") from exc
    if result.kind == "device":
        return JSONResponse(
            {"client_id": result.client_id, "kind": result.kind, "token": result.raw_credential}
        )
    response = JSONResponse({"client_id": result.client_id, "kind": result.kind})
    response.set_cookie(
        COOKIE_NAME,
        result.raw_credential,
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    return response


@router.get("/clients", response_model=list[ClientOut])
def list_clients(
    _requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> list[ClientOut]:
    return [ClientOut(**vars(c)) for c in pairing.list_clients(
        organization_id=_requester.organization_id,
    )]


@router.post("/clients/{client_id}/revoke")
def revoke_client(
    client_id: int,
    requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> dict[str, bool]:
    try:
        pairing.revoke_client(client_id=client_id, requester=str(requester.id),
                              organization_id=requester.organization_id)
    except ClientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"revoked": True}


@router.get("/me", response_model=ClientOut)
def me(client: Client = Depends(get_current_client)) -> ClientOut:
    return ClientOut(**vars(client))


class OrganizationOut(BaseModel):
    name: str
    logo_asset: str | None


@router.get("/organization", response_model=OrganizationOut)
@versioned_snapshot("settings")
def organization(
    request: Request,
    response: Response,
    client: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> OrganizationOut:
    found = pairing._pairing.find_organization(client.organization_id)
    if found is None:
        raise HTTPException(status_code=404, detail="organization not found")
    publishing = get_organization_services(request).publishing
    return OrganizationOut(
        name=found.name, logo_asset=publishing.get_branding_defaults().logo_asset,
    )


_LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg"}


@router.get("/branding/logo", response_class=FileResponse, dependencies=[Depends(enforce_throttle)])
def branding_logo(
    code: str, request: Request, pairing: DojoPairing = Depends(get_pairing),
) -> FileResponse:
    """Workspace logo for the pairing screen; only a still-usable code exposes it."""
    found = pairing.pending_code_organization(code=code)
    if found is None:
        raise HTTPException(status_code=404, detail="no logo")
    publishing = services_for_organization(request, found.id).publishing
    reference = publishing.get_branding_defaults().logo_asset
    if not reference or not reference.startswith("branding/assets/"):
        raise HTTPException(status_code=404, detail="no logo")
    try:
        path = BrandingAssets(publishing.media_root).resolve(
            reference.removeprefix("branding/assets/")
        )
    except BrandingAssetNotFound as exc:
        raise HTTPException(status_code=404, detail="no logo") from exc
    if path.suffix not in _LOGO_TYPES:
        raise HTTPException(status_code=404, detail="no logo")
    return FileResponse(
        path, media_type=_LOGO_TYPES[path.suffix],
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def get_publishing(request: Request) -> DojoPublishing:
    return get_organization_services(request).publishing


class PushTokenIn(BaseModel):
    token: str


@router.put("/me/push-token")
def put_push_token(
    body: PushTokenIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, bool]:
    try:
        publishing.register_push_token(client.id, body.token)
    except PushTokenInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/me/push-token")
def delete_push_token(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, bool]:
    publishing.remove_push_token(client.id)
    return {"ok": True}
