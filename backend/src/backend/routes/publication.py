from __future__ import annotations

from datetime import datetime
from typing import Literal

from dojo import (
    Client,
    DojoPublishing,
    MediaNotFound,
    PublicationInProgress,
    PublicationNotReady,
    RescheduleTimeInvalid,
    SkipRequiresConfirmation,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


# Unauthenticated: Meta fetches the approved render with an unguessable token.
fetch_router = APIRouter(tags=["publication"])


@fetch_router.get("/pub/{token}")
def fetch_artifact(token: str, request: Request) -> FileResponse:
    publishing: DojoPublishing = request.app.state.publishing
    try:
        path = publishing.serve_signed_artifact(token)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(str(path), media_type="video/mp4", filename="reel.mp4")


router = APIRouter(prefix="/api/packages/active/publication", tags=["publication"])


class RecoveryIn(BaseModel):
    action: Literal["review", "skip", "reschedule"]
    confirmed: bool = False
    new_due_at: datetime | None = None


@router.post("/recover", response_model=dict[str, object])
def recover_publication(
    body: RecoveryIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return {"publication": publishing.recover_publication(
            body.action, confirmed=body.confirmed, new_due_at=body.new_due_at,
            requester=str(client.id),
        )}
    except (PublicationInProgress, PublicationNotReady) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RescheduleTimeInvalid, SkipRequiresConfirmation) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=dict[str, object])
def publication_status(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    return {"publication": publishing.get_publication_status()}


@router.post("/retry", response_model=dict[str, object])
def retry_publication(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.retry_publication(requester=str(client.id))
    except PublicationInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PublicationNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reconcile", response_model=dict[str, object])
def reconcile_publication(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    return {"publication": publishing.reconcile_publication(requester=str(client.id))}
