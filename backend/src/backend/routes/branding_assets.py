from dojo import (
    BrandingAssetInvalid,
    BrandingAssetNotFound,
    BrandingAssets,
    BrandingAssetTooLarge,
    Client,
    DojoPublishing,
)
from dojo.branding_assets import MAX_BRANDING_BYTES
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.deps import get_current_client
from backend.routes.settings import get_publishing


class BrandingAssetOut(BaseModel):
    asset: str
    preview_url: str


router = APIRouter(prefix="/api/settings/branding/assets", tags=["branding assets"])


@router.post(
    "",
    response_model=BrandingAssetOut,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_branding_image(
    request: Request,
    _client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> BrandingAssetOut:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BRANDING_BYTES:
            raise HTTPException(status_code=413, detail="branding image exceeds 10 MiB")
        data.extend(chunk)
    try:
        asset = await run_in_threadpool(
            BrandingAssets(publishing.media_root).save_image, bytes(data)
        )
    except BrandingAssetTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except BrandingAssetInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BrandingAssetOut(
        asset=asset.reference, preview_url=f"/api/settings/branding/assets/{asset.asset_id}"
    )


@router.get("/{asset_id}", response_class=FileResponse)
def preview_branding_image(
    asset_id: str,
    _client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    try:
        path = BrandingAssets(publishing.media_root).resolve(asset_id)
    except BrandingAssetNotFound as exc:
        raise HTTPException(status_code=404, detail="branding asset not found") from exc
    return FileResponse(
        path,
        media_type="image/png" if path.suffix == ".png" else "image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
