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


class EditorMediaOut(CompletedMediaOut):
    is_video: bool
    source_duration: float | None
    effective_duration: float | None


class ActiveEditorOut(BaseModel):
    package: PackageOut
    render_stale: bool
    media: list[EditorMediaOut]
    montage: MontageOut


class CompletedPackageOut(BaseModel):
    folder_name: str
    media: list[CompletedMediaOut]
    order: list[str]
    caption: str | None
    render_revision: str | None
    artifacts: list[PackageArtifactOut]
