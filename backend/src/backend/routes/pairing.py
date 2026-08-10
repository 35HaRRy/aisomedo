from __future__ import annotations

from datetime import datetime
from typing import Literal

from dojo import Client, ClientNotFound, DojoPairing, PairingError
from dojo.pairing import CODE_TTL
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.deps import get_current_client

COOKIE_NAME = "dojo_session"
SESSION_MAX_AGE = 30 * 24 * 3600
TTL_SECONDS = int(CODE_TTL.total_seconds())


def get_pairing(request: Request) -> DojoPairing:
    return request.app.state.pairing


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


@router.post("/validate")
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
