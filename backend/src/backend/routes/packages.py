from __future__ import annotations

from datetime import datetime

from dojo import (
    ActivePackageExists,
    Client,
    DojoPublishing,
    MediaNotFound,
    MediaNotRemovable,
    MediaNotRestorable,
    NoActivePackage,
    PackageCompleted,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/packages", tags=["packages"])


class PackageOut(BaseModel):
    id: int
    folder_name: str
    created_at: datetime
    status: str


class DownloadIn(BaseModel):
    artifact_ref: str


class DownloadOut(BaseModel):
    url: str


@router.get("/active", response_model=PackageOut)
def get_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    package = publishing.get_or_create_active_package(requester=str(client.id))
    return PackageOut(**package.__dict__)


@router.post("/active", response_model=PackageOut, status_code=201)
def ensure_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.ensure_active_package(requester=str(client.id))
    except ActivePackageExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)


@router.post("/active/complete", response_model=PackageOut)
def complete_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.complete_active_package(requester=str(client.id))
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)


_MUTATION_STATUS = {
    NoActivePackage: 404,
    MediaNotFound: 404,
    MediaNotRemovable: 409,
    MediaNotRestorable: 409,
    PackageCompleted: 409,
}


def _map_mutation_error(exc: Exception) -> None:
    status = _MUTATION_STATUS.get(type(exc))
    if status is not None:
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/active/media/{media_id}/remove", status_code=200)
def remove_media(
    media_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, str]:
    try:
        publishing.remove_media(media_id, requester=str(client.id))
    except (NoActivePackage, MediaNotFound, MediaNotRemovable, PackageCompleted) as exc:
        _map_mutation_error(exc)
    return {"status": "removed"}


@router.post("/active/media/{media_id}/restore", status_code=200)
def restore_media(
    media_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, str]:
    try:
        publishing.restore_media(media_id, requester=str(client.id))
    except (NoActivePackage, MediaNotFound, MediaNotRestorable, PackageCompleted) as exc:
        _map_mutation_error(exc)
    return {"status": "restored"}


@router.get("", response_model=list[PackageOut])
def list_completed(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> list[PackageOut]:
    return [PackageOut(**p.__dict__) for p in publishing.list_completed_packages()]


@router.get("/{folder_name}", response_model=dict[str, object])
def browse_completed(
    folder_name: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.browse_completed_package(folder_name)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{folder_name}/download", response_model=DownloadOut)
def download_artifact(
    folder_name: str,
    body: DownloadIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> DownloadOut:
    try:
        url = publishing.create_download_url(folder_name, body.artifact_ref)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DownloadOut(url=url)
