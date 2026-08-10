from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Literal

from dojo import Client, ClientNotFound, DojoPairing, PairingError
from dojo.pairing import CODE_TTL
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.deps import COOKIE_NAME, SESSION_MAX_AGE, get_current_client

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
    name: str
    kind: str
    created_at: datetime
    created_by: str
    last_seen_at: datetime | None
    revoked_at: datetime | None


@router.post("/codes", response_model=CodeOut)
def create_code(
    requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> CodeOut:
    issued = pairing.create_pairing_code(requester=str(requester.id))
    return CodeOut(code=issued.raw_code, expires_at=issued.expires_at, ttl_seconds=TTL_SECONDS)


@router.post("/validate", dependencies=[Depends(enforce_throttle)])
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
    return [ClientOut(**vars(c)) for c in pairing.list_clients()]


@router.post("/clients/{client_id}/revoke")
def revoke_client(
    client_id: int,
    requester: Client = Depends(get_current_client),
    pairing: DojoPairing = Depends(get_pairing),
) -> dict[str, bool]:
    try:
        pairing.revoke_client(client_id=client_id, requester=str(requester.id))
    except ClientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"revoked": True}


@router.get("/me", response_model=ClientOut)
def me(client: Client = Depends(get_current_client)) -> ClientOut:
    return ClientOut(**vars(client))
