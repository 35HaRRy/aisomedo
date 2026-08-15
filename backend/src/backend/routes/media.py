from __future__ import annotations

from typing import Any

from dojo import (
    Client,
    DojoPublishing,
    PackageLimitExceeded,
    UploadChecksumMismatch,
    UploadConflict,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_current_client


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/media/uploads", tags=["media"])


class UploadInitIn(BaseModel):
    filename: str
    content_type: str
    declared_size_bytes: int


class UploadOut(BaseModel):
    upload_id: str
    received_bytes: int
    declared_size_bytes: int
    status: str
    received_ranges: list[list[int]]
    error_reason: str | None = None


def _out(status: Any) -> UploadOut:
    return UploadOut(**status.__dict__)


@router.post("", response_model=UploadOut, status_code=201)
def init_upload(
    body: UploadInitIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    try:
        status = publishing.start_upload(
            body.filename, body.content_type, body.declared_size_bytes, requester=str(client.id)
        )
    except UploadInvalidFilename as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except PackageLimitExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _out(status)


@router.put("/{upload_id}/ranges", response_model=UploadOut)
async def append_range(
    upload_id: str,
    offset: int,
    checksum_sha256: str,
    request: Request,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    body = await request.body()
    length = len(body)
    if length > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="chunk exceeds 8 MiB limit")
    try:
        status = publishing.append_upload_range(
            upload_id, offset, length, checksum_sha256, body
        )
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadNotReceiving as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadChecksumMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _out(status)


@router.get("", response_model=list[UploadOut])
def list_uploads(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> list[UploadOut]:
    return [_out(status) for status in publishing.list_active_uploads()]


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(
    upload_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    try:
        status = publishing.get_upload_status(upload_id)
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _out(status)


@router.post("/{upload_id}/complete", response_model=UploadOut)
def complete_upload(
    upload_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> UploadOut:
    try:
        status = publishing.complete_upload(upload_id, requester=str(client.id))
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadIncomplete as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _out(status)


@router.post("/{upload_id}/abort", status_code=200)
def abort_upload(
    upload_id: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, str]:
    try:
        publishing.abort_upload(upload_id, requester=str(client.id))
    except UploadNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "aborted"}
