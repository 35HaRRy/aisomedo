from __future__ import annotations

from typing import NoReturn
from urllib.parse import quote, urlencode

from dojo import (
    ActivePackageExists,
    Client,
    DojoPublishing,
    LegacyTrimConflict,
    LogoNotConfigured,
    MediaNotFound,
    MediaNotRemovable,
    MediaNotRestorable,
    MontageDurationExceeded,
    MontageOrderInvalid,
    MontageTrimInvalid,
    NoActivePackage,
    PackageArtifact,
    PackageChanged,
    PackageCompleted,
    PackageLimitExceeded,
    PublicationInProgress,
    PublicationNotReady,
    UploadConflict,
    UploadInvalidFilename,
    UploadTooLarge,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.deps import get_current_client
from backend.routes.package_models import (
    ActiveEditorOut,
    ClearPackageIn,
    ClearPackageOut,
    CompletedPackageOut,
    MontageOut,
    PackageOut,
    RenderIn,
    RenderOut,
    SelectionIn,
)


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


router = APIRouter(prefix="/api/packages", tags=["packages"])


class DownloadIn(BaseModel):
    artifact_ref: str


class DownloadOut(BaseModel):
    url: str


class OrderIn(BaseModel):
    order: list[str]
    expected_folder_name: str | None = None


class TrimsIn(BaseModel):
    trims: dict[str, dict[str, float]]


class CaptionIn(BaseModel):
    caption: str


class BrandingIn(BaseModel):
    branding: dict[str, object]


@router.get("/active", response_model=PackageOut)
def get_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.get_or_create_active_package(requester=str(client.id))
    except PublicationInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)


@router.post("/active", response_model=PackageOut, status_code=201)
def ensure_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> PackageOut:
    try:
        package = publishing.ensure_active_package(requester=str(client.id))
    except (ActivePackageExists, PublicationInProgress) as exc:
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
    except PublicationNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PackageOut(**package.__dict__)


_MUTATION_STATUS: dict[type[Exception], int] = {
    NoActivePackage: 404,
    MediaNotFound: 404,
    MediaNotRemovable: 409,
    MediaNotRestorable: 409,
    PackageCompleted: 409,
    MontageOrderInvalid: 422,
    MontageTrimInvalid: 422,
    MontageDurationExceeded: 409,
    PackageChanged: 409,
    LegacyTrimConflict: 409,
    ValueError: 400,
}


def _map_mutation_error(exc: Exception) -> NoReturn:
    status = _MUTATION_STATUS.get(type(exc))
    if status is not None:
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    raise exc


def _file(artifact: PackageArtifact, *, download: bool) -> FileResponse:
    return FileResponse(
        artifact.path, media_type=artifact.content_type, filename=artifact.filename,
        content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def _artifact_url(folder: str, reference: str, *, download: bool) -> str:
    return f"/api/packages/{quote(folder, safe='')}/artifacts?" + urlencode({
        "artifact_ref": reference, "download": "true" if download else "false",
    })


def _completed_artifacts(folder: str, artifacts: list[dict]) -> list[dict]:
    return [{**item,
             "url": _artifact_url(folder, item["artifact_ref"], download=True)
             if item["available"] else None,
             "preview_url": _artifact_url(folder, item["artifact_ref"], download=False)
             if item["available"] and item["kind"] != "original" else None}
            for item in artifacts]


@router.get("/active/editor", response_model=ActiveEditorOut)
def get_editor(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    try:
        snapshot = publishing.get_active_editor()
    except (NoActivePackage, MediaNotFound) as exc:
        _map_mutation_error(exc)
    folder = snapshot["package"]["folder_name"]
    snapshot["render_preview_url"] = (
        "/api/packages/active/render/preview?" + urlencode({
            "expected_folder_name": folder, "revision": snapshot["render_revision"],
        }) if snapshot["render_status"] == "ready" else None
    )
    for media in snapshot["media"]:
        url = (f"/api/packages/active/media/{quote(media['media_id'], safe='')}/preview?"
               + urlencode({"expected_folder_name": folder})) if media["preview_ref"] else None
        media["preview_url"] = url
        media["artifacts"] = [{**artifact,
                               "url": url if artifact["kind"] == "processed" else None,
                               "preview_url": url if artifact["kind"] == "processed" else None}
                              for artifact in media["artifacts"]]
    return snapshot


@router.put("/active/selections", response_model=MontageOut)
def set_selections(
    body: SelectionIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    try:
        return publishing.set_selections(
            body.model_dump()["selections"], requester=str(client.id),
            expected_folder_name=body.expected_folder_name,
            photo_durations=body.photo_durations,
        ).to_dict()
    except (NoActivePackage, MediaNotFound, PackageCompleted, PackageChanged,
            MontageTrimInvalid, MontageDurationExceeded) as exc:
        _map_mutation_error(exc)


@router.post("/active/render", response_model=RenderOut)
def render_active(
    body: RenderIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    try:
        return publishing.render_preview(
            expected_folder_name=body.expected_folder_name, retry=body.retry,
        )
    except LogoNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (NoActivePackage, PackageChanged, MontageDurationExceeded, MontageTrimInvalid) as exc:
        _map_mutation_error(exc)


@router.get("/active/render/preview")
def render_file(
    expected_folder_name: str,
    revision: str | None = None,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    try:
        artifact = publishing.get_render_preview(
            expected_folder_name=expected_folder_name, expected_revision=revision,
        )
        return _file(artifact, download=False)
    except (NoActivePackage, MediaNotFound, PackageChanged, ValueError) as exc:
        _map_mutation_error(exc)


@router.post("/active/clear", response_model=ClearPackageOut)
def clear_package(
    body: ClearPackageIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    if not body.confirmed:
        raise HTTPException(status_code=409, detail="explicit confirmation required")
    try:
        return publishing.clear_active_package(expected_folder_name=body.expected_folder_name,
                                               expected_package_id=body.expected_package_id)
    except (NoActivePackage, PackageChanged, ValueError) as exc:
        _map_mutation_error(exc)
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="package cleanup failed; refresh before retrying",
        ) from exc


@router.get("/active/media/{media_id}/preview")
def media_preview(
    media_id: str,
    expected_folder_name: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    try:
        artifact = publishing.get_media_preview(media_id, expected_folder_name=expected_folder_name)
        return _file(artifact, download=False)
    except (NoActivePackage, MediaNotFound, PackageChanged, ValueError) as exc:
        _map_mutation_error(exc)


@router.post("/active/media/{media_id}/remove", status_code=200)
def remove_media(
    media_id: str,
    expected_folder_name: str | None = None,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, str]:
    try:
        publishing.remove_media(media_id, requester=str(client.id),
                                expected_folder_name=expected_folder_name)
    except (NoActivePackage, MediaNotFound, MediaNotRemovable,
            PackageCompleted, PackageChanged) as exc:
        _map_mutation_error(exc)
    return {"status": "removed"}


@router.post("/active/media/{media_id}/restore", status_code=200)
def restore_media(
    media_id: str,
    expected_folder_name: str | None = None,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, str]:
    try:
        publishing.restore_media(media_id, requester=str(client.id),
                                 expected_folder_name=expected_folder_name)
    except (NoActivePackage, MediaNotFound, MediaNotRestorable,
            PackageCompleted, PackageChanged) as exc:
        _map_mutation_error(exc)
    return {"status": "restored"}


@router.get("/active/montage", response_model=MontageOut)
def get_montage(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.get_montage_status().to_dict()
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/order", response_model=MontageOut)
def set_order(
    body: OrderIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.set_order(body.order, requester=str(client.id),
                                    expected_folder_name=body.expected_folder_name).to_dict()
    except (NoActivePackage, MediaNotFound, PackageCompleted, PackageChanged) as exc:
        _map_mutation_error(exc)
    except MontageOrderInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MontageTrimInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MontageDurationExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return publishing.get_montage_status().to_dict()


@router.put("/active/trims", response_model=MontageOut)
def set_trims(
    body: TrimsIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.set_trims(body.trims, requester=str(client.id)).to_dict()
    except (NoActivePackage, MediaNotFound, PackageCompleted, LegacyTrimConflict) as exc:
        _map_mutation_error(exc)
    except MontageTrimInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MontageDurationExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return publishing.get_montage_status().to_dict()


@router.get("/active/caption", response_model=dict[str, object])
def get_caption(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return {"caption": publishing.get_draft_caption()}
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/caption", response_model=dict[str, object])
def set_caption(
    body: CaptionIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        caption = publishing.set_caption(body.caption, requester=str(client.id))
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"caption": caption}


@router.get("/active/branding", response_model=dict[str, object])
def get_branding(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.get_draft_branding()
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/branding", response_model=dict[str, object])
def set_branding(
    body: BrandingIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.set_branding(body.branding, requester=str(client.id))
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/active/publish", response_model=dict[str, object])
def publish_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        result = publishing.publish(requester=str(client.id))
    except LogoNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PublicationInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PublicationNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(result, dict):
        status = result.get("status")
        if status in ("failed", "uncertain"):
            raise HTTPException(status_code=502, detail=result.get("error") or status)
        return {"status": "published", "publication": result}
    return {"status": "published"}


@router.get("/recovered", response_model=dict[str, object])
def list_recovered(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    return {"recovered": publishing.list_recovered_folders()}


@router.post("/recovered/{folder_name}/import", response_model=dict[str, object])
def import_recovered(
    folder_name: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.import_recovered_media(folder_name, requester=str(client.id))
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadInvalidFilename as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (NoActivePackage, PackageLimitExceeded, UploadConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recovered/{folder_name}/resolve", response_model=dict[str, object])
def resolve_recovered(
    folder_name: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        resolved = publishing.mark_recovered_resolved(folder_name, requester=str(client.id))
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"resolved": resolved}


@router.get("", response_model=list[PackageOut])
def list_completed(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> list[PackageOut]:
    return [PackageOut(**p.__dict__) for p in publishing.list_completed_packages()]


@router.get("/{folder_name}/artifacts")
def completed_artifact(
    folder_name: str,
    artifact_ref: str,
    download: bool = False,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    try:
        artifact = publishing.resolve_completed_artifact(folder_name, artifact_ref)
        return _file(artifact, download=download)
    except (MediaNotFound, ValueError) as exc:
        _map_mutation_error(exc)


@router.get("/{folder_name}", response_model=CompletedPackageOut)
def browse_completed(
    folder_name: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        view = publishing.browse_completed_package(folder_name)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    artifacts = _completed_artifacts(folder_name, view["artifacts"])
    view["artifacts"] = artifacts
    for media in view["media"]:
        items = [a for a in artifacts if a["kind"] != "render"
                 and a["artifact_ref"].split("/")[1] == media["media_id"]]
        media["artifacts"] = items
        media["preview_url"] = next((a["preview_url"] for a in items
                                     if a["kind"] == "processed" and a["available"]), None)
    return view


@router.post("/{folder_name}/download", response_model=DownloadOut)
def download_artifact(
    folder_name: str,
    body: DownloadIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> DownloadOut:
    try:
        publishing.resolve_completed_artifact(folder_name, body.artifact_ref)
        url = _artifact_url(folder_name, body.artifact_ref, download=True)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DownloadOut(url=url)
