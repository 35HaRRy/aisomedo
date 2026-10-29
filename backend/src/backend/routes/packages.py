from __future__ import annotations

import re
from collections.abc import Callable
from functools import wraps
from typing import Annotated, NoReturn, cast
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
    PackageEditConflict,
    PackageLimitExceeded,
    PublicationInProgress,
    PublicationNotReady,
    UploadConflict,
    UploadInvalidFilename,
    UploadTooLarge,
)
from dojo.package_state import GroupEdit
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.deps import get_current_client
from backend.routes.package_models import (
    ActiveEditorOut,
    ClearPackageIn,
    ClearPackageOut,
    CompletedPackageOut,
    MontageOut,
    PackageEditConflictOut,
    PackageEditIn,
    PackageOut,
    RenderIn,
    RenderOut,
    SectionPreviewRetryIn,
    SelectionIn,
)
from backend.snapshots import versioned_snapshot


def get_publishing(request: Request) -> DojoPublishing:
    return request.app.state.publishing


def require_package_revision(
    if_match: Annotated[str | None, Header()] = None,
) -> tuple[int, int]:
    if if_match is None:
        raise HTTPException(428, "displayed package revision required")
    match = re.fullmatch(r'"([1-9][0-9]{0,18}):([1-9][0-9]{0,18})"', if_match)
    if match is None:
        raise HTTPException(422, "If-Match must contain the quoted package-id:revision")
    return int(match[1]), int(match[2])


def _conditional_package_endpoint[**P, T](method: Callable[P, T]) -> Callable[P, T]:
    @wraps(method)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        publishing = cast(DojoPublishing, kwargs["publishing"])
        revision = cast(tuple[int, int], kwargs["revision"])
        try:
            # Acquire/use/release in one endpoint worker context, not across a
            # yield dependency whose thread/context may change on teardown.
            with publishing.conditional_package_operation(
                *revision, allow_missing=method.__name__ == "clear_package",
            ):
                return method(*args, **kwargs)
        except (NoActivePackage, PackageChanged) as exc:
            _map_mutation_error(exc)
    return guarded


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
@versioned_snapshot("package")
def get_active(
    request: Request, response: Response,
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
@_conditional_package_endpoint
def complete_active(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
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
    if isinstance(exc, PackageEditConflict):
        raise HTTPException(409, detail={
            "code": "edit_conflict", "content_revision": exc.content_revision,
            "conflicts": exc.conflicts,
        }) from exc
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
@versioned_snapshot("package")
def get_editor(
    request: Request, response: Response,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    try:
        snapshot = publishing.get_active_editor()
    except (NoActivePackage, MediaNotFound) as exc:
        _map_mutation_error(exc)
    return _editor_out(snapshot)


def _editor_out(snapshot: dict) -> dict:
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
        identity = {"expected_package_id": snapshot["package"]["id"],
                    "expected_folder_name": folder}
        prefix = f"/api/packages/active/media/{quote(media['media_id'], safe='')}"
        media["original_url"] = (prefix + "/original?" + urlencode(identity)
                                 if media.get("original_ref") else None)
        media["thumbnail_url"] = (prefix + "/thumbnail?" + urlencode({
            **identity, "generation": media["thumbnail_generation"],
        }) if media.get("thumbnail_ref") else None)
        section = media.get("section_preview")
        if section is not None:
            section["url"] = (prefix + "/sections/preview?" + urlencode({
                **identity, "generation": section["generation"],
            }) if section.get("status") == "ready" and section.get("artifact_ref") else None)
        media["artifacts"] = [{**artifact,
                               "url": url if artifact["kind"] == "processed" else None,
                               "preview_url": url if artifact["kind"] == "processed" else None}
                              for artifact in media["artifacts"]]
    return snapshot


@router.put("/active/edits", response_model=ActiveEditorOut,
            responses={409: {"model": PackageEditConflictOut}})
def apply_edits(
    body: PackageEditIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    try:
        snapshot = publishing.apply_package_edits(
            body.expected_package_id, body.expected_folder_name, body.base_content_revision,
            [GroupEdit(e.key, e.base, e.proposed) for e in body.changes], requester=str(client.id),
        )
    except (NoActivePackage, MediaNotFound, PackageChanged,
            MontageTrimInvalid, MontageDurationExceeded) as exc:
        _map_mutation_error(exc)
    return _editor_out(snapshot)


@router.put("/active/selections", response_model=MontageOut)
@_conditional_package_endpoint
def set_selections(
    body: SelectionIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
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
@_conditional_package_endpoint
def render_active(
    body: RenderIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
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
@_conditional_package_endpoint
def clear_package(
    body: ClearPackageIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
) -> dict:
    if not body.confirmed:
        raise HTTPException(status_code=409, detail="explicit confirmation required")
    if revision[0] != body.expected_package_id:
        raise HTTPException(status_code=409, detail="cleanup package identity changed")
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


def _active_media_file(
    publishing: DojoPublishing, media_id: str, kind: str, package_id: int, folder: str,
    generation: str | None = None,
) -> FileResponse:
    try:
        return _file(publishing.get_active_media_artifact(
            media_id, kind, expected_package_id=package_id,
            expected_folder_name=folder, generation=generation,
        ), download=False)
    except (NoActivePackage, MediaNotFound, PackageChanged, ValueError) as exc:
        _map_mutation_error(exc)


@router.get("/active/media/{media_id}/original")
def original_media(
    media_id: str, expected_package_id: int, expected_folder_name: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    return _active_media_file(publishing, media_id, "original",
                              expected_package_id, expected_folder_name)


@router.get("/active/media/{media_id}/thumbnail")
def media_thumbnail(
    media_id: str, expected_package_id: int, expected_folder_name: str,
    generation: str | None = None,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    return _active_media_file(publishing, media_id, "thumbnail", expected_package_id,
                              expected_folder_name, generation)


@router.get("/active/media/{media_id}/sections/preview")
def media_sections_preview(
    media_id: str, expected_package_id: int, expected_folder_name: str, generation: str,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> FileResponse:
    return _active_media_file(publishing, media_id, "section_preview", expected_package_id,
                              expected_folder_name, generation)


@router.post("/active/media/{media_id}/sections/retry", response_model=ActiveEditorOut)
def retry_media_sections_preview(
    media_id: str, body: SectionPreviewRetryIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict:
    try:
        return _editor_out(publishing.retry_section_preview(media_id, **body.model_dump()))
    except (NoActivePackage, MediaNotFound, PackageChanged) as exc:
        _map_mutation_error(exc)


@router.post("/active/media/{media_id}/remove", status_code=200)
@_conditional_package_endpoint
def remove_media(
    media_id: str,
    expected_folder_name: str | None = None,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
) -> dict[str, str]:
    try:
        publishing.remove_media(media_id, requester=str(client.id),
                                expected_folder_name=expected_folder_name)
    except (NoActivePackage, MediaNotFound, MediaNotRemovable,
            PackageCompleted, PackageChanged) as exc:
        _map_mutation_error(exc)
    return {"status": "removed"}


@router.post("/active/media/{media_id}/restore", status_code=200)
@_conditional_package_endpoint
def restore_media(
    media_id: str,
    expected_folder_name: str | None = None,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
) -> dict[str, str]:
    try:
        publishing.restore_media(media_id, requester=str(client.id),
                                 expected_folder_name=expected_folder_name)
    except (NoActivePackage, MediaNotFound, MediaNotRestorable,
            PackageCompleted, PackageChanged) as exc:
        _map_mutation_error(exc)
    return {"status": "restored"}


@router.get("/active/montage", response_model=MontageOut)
@versioned_snapshot("package")
def get_montage(
    request: Request, response: Response,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.get_montage_status().to_dict()
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/order", response_model=MontageOut)
@_conditional_package_endpoint
def set_order(
    body: OrderIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
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
@_conditional_package_endpoint
def set_trims(
    body: TrimsIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
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
@versioned_snapshot("package")
def get_caption(
    request: Request, response: Response,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return {"caption": publishing.get_draft_caption()}
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/caption", response_model=dict[str, object])
@_conditional_package_endpoint
def set_caption(
    body: CaptionIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
) -> dict[str, object]:
    try:
        caption = publishing.set_caption(body.caption, requester=str(client.id))
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"caption": caption}


@router.get("/active/branding", response_model=dict[str, object])
@versioned_snapshot("package")
def get_branding(
    request: Request, response: Response,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.get_draft_branding()
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/branding", response_model=dict[str, object])
@_conditional_package_endpoint
def set_branding(
    body: BrandingIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
    revision: tuple[int, int] = Depends(require_package_revision),
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
@versioned_snapshot("dashboard")
def list_recovered(
    request: Request, response: Response,
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
@versioned_snapshot("completed")
def list_completed(
    request: Request, response: Response,
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
@versioned_snapshot("completed")
def browse_completed(
    request: Request, response: Response,
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
        thumbnail = media.pop("thumbnail_ref", None)
        media["thumbnail_url"] = None
        if thumbnail:
            try:
                publishing.resolve_completed_artifact(folder_name, thumbnail)
                media["thumbnail_url"] = _artifact_url(folder_name, thumbnail, download=False)
            except (MediaNotFound, ValueError):
                pass  # Older archives may no longer contain their generated thumbnail.
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
