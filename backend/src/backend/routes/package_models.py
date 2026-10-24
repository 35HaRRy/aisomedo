from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PackageOut(BaseModel):
    id: int
    folder_name: str
    created_at: datetime
    status: str


class VideoRangeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    end: Annotated[float, Field(strict=True, allow_inf_nan=False)]

    @field_validator("start", "end", mode="before")
    @classmethod
    def json_safe_invalid_number(cls, value: object) -> object:
        # FastAPI echoes validation inputs in JSON errors. Non-finite values
        # must remain invalid without making that 422 response unserializable.
        return None if isinstance(value, float) and not isfinite(value) else value


class SelectionIn(BaseModel):
    expected_folder_name: str
    selections: dict[str, list[VideoRangeOut]]
    photo_durations: (
        dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.04)]] | None
    ) = None

    @field_validator("photo_durations", mode="before")
    @classmethod
    def finite_photo_durations(cls, value: object) -> object:
        if isinstance(value, dict):
            return {key: None if isinstance(seconds, float) and not isfinite(seconds) else seconds
                    for key, seconds in value.items()}
        return value


class GroupEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    base: dict[str, object]
    proposed: dict[str, object]


class PackageEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_package_id: Annotated[int, Field(strict=True, gt=0)]
    expected_folder_name: str
    base_content_revision: Annotated[int, Field(strict=True, gt=0)]
    changes: list[GroupEditIn]


class GroupConflictOut(BaseModel):
    key: str
    current: dict[str, object]


class EditConflictOut(BaseModel):
    code: Literal["edit_conflict"]
    content_revision: int
    conflicts: list[GroupConflictOut]


class PackageEditConflictOut(BaseModel):
    detail: EditConflictOut


class RenderIn(BaseModel):
    expected_folder_name: str
    retry: bool = False


class RenderOut(BaseModel):
    stale: bool
    render_revision: str


class ClearPackageIn(BaseModel):
    expected_folder_name: str
    expected_package_id: int
    confirmed: Annotated[bool, Field(strict=True)]


class ClearPackageOut(BaseModel):
    folder_name: str
    upload_ids: list[str]


class MontageClipOut(BaseModel):
    media_id: str
    filename: str
    content_type: str
    is_video: bool
    source_duration: float | None
    effective_duration: float


class MontageOut(BaseModel):
    order: list[str]
    trims: dict[str, VideoRangeOut]
    selections: dict[str, list[VideoRangeOut]]
    clips: list[MontageClipOut]
    combined_duration: float
    max_duration_seconds: float
    over_limit: bool
    required_action: str | None
    card_duration: float
    duration_complete: bool


class PackageArtifactOut(BaseModel):
    artifact_ref: str
    kind: Literal["original", "processed", "render"]
    filename: str
    content_type: str
    available: bool
    url: str | None
    preview_url: str | None


class ProcessedMetadataOut(BaseModel):
    path: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    dimensions: list[int] | None = None
    duration: float | None = None


class MediaOut(BaseModel):
    media_id: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    status: str
    processed: ProcessedMetadataOut
    removed_position: int | None = None


class CompletedMediaOut(MediaOut):
    preview_url: str | None
    artifacts: list[PackageArtifactOut]


class SectionPreviewOut(BaseModel):
    status: Literal["missing", "queued", "processing", "ready", "failed"] = "missing"
    generation: str | None = None
    url: str | None = None
    duration: float | None = None


class SectionPreviewRetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_package_id: Annotated[int, Field(strict=True, gt=0)]
    expected_folder_name: str
    expected_generation: Annotated[str, Field(min_length=1, max_length=128)]


class EditorMediaOut(CompletedMediaOut):
    is_video: bool
    source_duration: float | None
    effective_duration: float | None
    original_url: str | None = None
    thumbnail_url: str | None = None
    section_preview: SectionPreviewOut | None = None


class ActiveEditorOut(BaseModel):
    content_revision: int
    view_revision: int
    package: PackageOut
    render_stale: bool
    media: list[EditorMediaOut]
    montage: MontageOut
    render_status: Literal[
        "missing", "stale", "queued", "processing", "ready", "failed",
    ] = "missing"
    render_revision: str | None = None
    render_preview_url: str | None = None
    render_duration: float | None = None


class CompletedPackageOut(BaseModel):
    folder_name: str
    media: list[CompletedMediaOut]
    order: list[str]
    caption: str | None
    render_revision: str | None
    artifacts: list[PackageArtifactOut]
