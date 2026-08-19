from __future__ import annotations

from datetime import date, time

from dojo import (
    BrandingConfig,
    Client,
    DojoPublishing,
    ManualPublishConflict,
    PlanInvalid,
    SchedulePlan,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


class BrandingDefaultsIn(BaseModel):
    logo_asset: str | None = None
    intro_asset: str | None = None
    intro_duration: float | None = None
    outro_asset: str | None = None
    outro_duration: float | None = None
    caption_template: str | None = None


class BrandingDefaultsOut(BaseModel):
    logo_asset: str | None
    intro_asset: str | None
    intro_duration: float | None
    outro_asset: str | None
    outro_duration: float | None
    caption_template: str | None


class PlanIn(BaseModel):
    anchor_date: date | None = None
    anchor_time: time | None = None
    enabled: bool = True


class PlanOut(BaseModel):
    anchor_date: str | None
    anchor_time: str | None
    enabled: bool
    timezone: str


class OccurrenceOut(BaseModel):
    id: int
    kind: str
    due_at: str
    status: str


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/branding", response_model=BrandingDefaultsOut)
def get_branding_defaults(
    _client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> BrandingDefaultsOut:
    return BrandingDefaultsOut(**publishing.get_branding_defaults().to_dict())


@router.put("/branding", response_model=BrandingDefaultsOut)
def set_branding_defaults(
    body: BrandingDefaultsIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> BrandingDefaultsOut:
    config = publishing.set_branding_defaults(
        BrandingConfig(**body.model_dump()), requester=str(client.id)
    )
    return BrandingDefaultsOut(**config.to_dict())


@router.get("/plan", response_model=PlanOut)
def get_plan(
    _client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PlanOut:
    return PlanOut(**publishing.get_plan().to_dict())


@router.put("/plan", response_model=PlanOut)
def set_plan(
    body: PlanIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PlanOut:
    plan = SchedulePlan(
        anchor_date=body.anchor_date,
        anchor_time=body.anchor_time,
        enabled=body.enabled,
    )
    try:
        updated = publishing.set_plan(plan, requester=str(client.id))
    except PlanInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlanOut(**updated.to_dict())


@router.post("/manual-publish", response_model=OccurrenceOut)
def manual_publish(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> OccurrenceOut:
    try:
        occurrence = publishing.manual_publish(requester=str(client.id))
    except ManualPublishConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OccurrenceOut(
        id=occurrence.id,
        kind=occurrence.kind,
        due_at=occurrence.due_at.isoformat(),
        status=occurrence.status,
    )
