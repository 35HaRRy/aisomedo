from __future__ import annotations

from dojo import BrandingConfig, Client, DojoPublishing
from fastapi import APIRouter, Depends, Request
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