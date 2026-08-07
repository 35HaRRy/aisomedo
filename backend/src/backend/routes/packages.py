from __future__ import annotations

from datetime import datetime

from dojo import ActivePackageExists, DojoPublishing
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/packages", tags=["packages"])


class PackageOut(BaseModel):
    id: int
    folder_name: str
    created_at: datetime
    status: str


@router.get("/active", response_model=PackageOut)
def get_active(publishing: DojoPublishing = Depends(get_publishing)) -> PackageOut:
    package = publishing.get_active_package()
    if package is None:
        raise HTTPException(status_code=404, detail="no active package")
    return PackageOut(**package.__dict__)


@router.post("/active", response_model=PackageOut, status_code=201)
def ensure_active(publishing: DojoPublishing = Depends(get_publishing)) -> PackageOut:
    try:
        package = publishing.ensure_active_package()
    except ActivePackageExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)
