from __future__ import annotations

from datetime import datetime
from typing import Literal

from dojo import (
    Client,
    DojoPublishing,
    ManualPublishConflict,
    MediaNotFound,
    PublicationInProgress,
    PublicationNotReady,
    RescheduleTimeInvalid,
    SkipRequiresConfirmation,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.deps import get_current_client
from backend.snapshots import versioned_snapshot


def get_publishing(request: Request) -> DojoPublishing:
    from backend.organizations import get_organization_services

    return get_organization_services(request).publishing


# Unauthenticated: Meta fetches the approved render with an unguessable token.
fetch_router = APIRouter(tags=["publication"])


@fetch_router.get("/pub/{token}")
def fetch_artifact(token: str, request: Request) -> FileResponse:
    from dojo.exceptions import OrganizationInactive, OrganizationNotFound
    from dojo.organizations import DojoOrganizations

    from backend.organizations import services_for_organization

    template = getattr(request.app.state, "publishing", None)
    if template is None:
        raise HTTPException(status_code=404, detail="signed artifact not found")
    try:
        owner_reader = getattr(template._signed_urls, "token_owner", None)
        owner = owner_reader(token) if owner_reader is not None else None
        if owner is None:
            owner = template._packages.organization_id
        if owner is None:
            raise MediaNotFound("signed artifact not found")
        DojoOrganizations(request.app.state.pairing._pairing).require_active(owner)
        publishing = services_for_organization(request, owner).publishing
        path = publishing.serve_signed_artifact(token)
    except (MediaNotFound, ValueError, OrganizationInactive, OrganizationNotFound) as exc:
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
    except (PublicationInProgress, PublicationNotReady, ManualPublishConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RescheduleTimeInvalid, SkipRequiresConfirmation) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=dict[str, object])
@versioned_snapshot("publication")
def publication_status(
    request: Request, response: Response,
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
