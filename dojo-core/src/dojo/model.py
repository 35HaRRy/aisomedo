from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

PACKAGE_FOLDER_FORMAT = "%d-%m-%Y %H-%M"

KEEP_BOTH = "keep_both"
KEEP_SELECTED = "keep_selected"
KEEP_TARGET = "keep_target"
CONFLICT_DECISIONS = (KEEP_BOTH, KEEP_SELECTED, KEEP_TARGET)


@dataclass(frozen=True)
class Package:
    id: int
    folder_name: str
    created_at: datetime
    status: str = "active"


@dataclass(frozen=True)
class Manifest:
    media: list[dict] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    trims: dict = field(default_factory=dict)
    caption: str | None = None
    branding: dict = field(default_factory=dict)
    render_revision: str | None = None
    meta: dict = field(default_factory=dict)
    recovery: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "media": self.media,
            "order": self.order,
            "trims": self.trims,
            "caption": self.caption,
            "branding": self.branding,
            "render_revision": self.render_revision,
            "meta": self.meta,
            "recovery": self.recovery,
        }


@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor: str
    occurred_at: datetime
    details: dict = field(default_factory=dict)
    id: int = 0


@dataclass(frozen=True)
class PairingCode:
    id: int
    code_hash: str
    expires_at: datetime
    created_by: str
    created_at: datetime
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class PairingCodeIssued:
    raw_code: str
    expires_at: datetime


@dataclass(frozen=True)
class Client:
    id: int
    name: str
    kind: str
    created_at: datetime
    created_by: str
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class PairingResult:
    client_id: int
    kind: str
    raw_credential: str


@dataclass(frozen=True)
class ActivityEntry:
    id: int
    action: str
    occurred_at: datetime
    details: dict
    actor: Client | str


@dataclass(frozen=True)
class ActivityPage:
    entries: list[ActivityEntry]
    next_cursor: int | None


@dataclass(frozen=True)
class ConsentPolicy:
    version: int
    text: str
    created_at: datetime
    created_by: str
    id: int = 0


@dataclass(frozen=True)
class ConsentAcceptance:
    policy_version: int
    accepted_at: datetime
    accepting_client_id: int
    accepting_client_name: str
    accepting_client_kind: str
    id: int = 0


@dataclass(frozen=True)
class SetupItem:
    key: str
    label: str
    complete: bool


@dataclass(frozen=True)
class MediaEntry:
    media_id: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    status: str = "finalized"
    processed: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "media_id": self.media_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "uploaded_at": self.uploaded_at.isoformat(),
            "status": self.status,
            "processed": self.processed,
        }


@dataclass(frozen=True)
class Upload:
    id: int
    upload_id: str
    package_id: int
    filename: str
    content_type: str
    declared_size_bytes: int
    received_ranges: list[list[int]]
    received_bytes: int
    status: str
    created_at: datetime
    updated_at: datetime
    error_reason: str | None = None
    conflict_decision: str | None = None
    conflict_target_media_id: str | None = None


@dataclass(frozen=True)
class UploadStatus:
    upload_id: str
    received_bytes: int
    declared_size_bytes: int
    status: str
    received_ranges: list[list[int]]
    error_reason: str | None = None
    conflicts: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Job:
    id: int
    job_id: str
    upload_id: int | None
    kind: str
    status: str
    payload: dict
    created_at: datetime
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    error_reason: str | None = None


@dataclass(frozen=True)
class ProcessedMedia:
    original_path: Path
    processed_path: Path
    content_type: str
    size_bytes: int
    dimensions: tuple[int, int] | None = None
    duration: float | None = None


@dataclass(frozen=True)
class UploadLimits:
    max_file_bytes: int
    max_package_bytes: int


@dataclass(frozen=True)
class BrandingConfig:
    logo_asset: str | None = None
    intro_asset: str | None = None
    intro_duration: float | None = None
    outro_asset: str | None = None
    outro_duration: float | None = None
    caption_template: str | None = None

    def to_dict(self) -> dict:
        return {
            "logo_asset": self.logo_asset,
            "intro_asset": self.intro_asset,
            "intro_duration": self.intro_duration,
            "outro_asset": self.outro_asset,
            "outro_duration": self.outro_duration,
            "caption_template": self.caption_template,
        }


@dataclass(frozen=True)
class MontageLimits:
    max_duration_seconds: float
    photo_duration_seconds: float


@dataclass(frozen=True)
class MontageClip:
    media_id: str
    filename: str
    content_type: str
    is_video: bool
    source_duration: float | None = None
    effective_duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "media_id": self.media_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "is_video": self.is_video,
            "source_duration": self.source_duration,
            "effective_duration": self.effective_duration,
        }


@dataclass(frozen=True)
class MontageStatus:
    order: list[str]
    trims: dict
    clips: list[MontageClip]
    combined_duration: float
    max_duration_seconds: float
    over_limit: bool
    required_action: str | None = None

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "trims": self.trims,
            "clips": [c.to_dict() for c in self.clips],
            "combined_duration": self.combined_duration,
            "max_duration_seconds": self.max_duration_seconds,
            "over_limit": self.over_limit,
            "required_action": self.required_action,
        }


@dataclass(frozen=True)
class ReelClip:
    media_id: str
    path: Path
    is_video: bool
    duration: float
    trim_start: float = 0.0
    trim_end: float | None = None


@dataclass(frozen=True)
class ReelBuild:
    """Immutable snapshot of everything the renderer needs to produce one Reel."""

    clips: list[ReelClip]
    photo_duration: float
    logo_asset: Path | None = None
    intro_asset: Path | None = None
    intro_duration: float | None = None
    outro_asset: Path | None = None
    outro_duration: float | None = None


@dataclass(frozen=True)
class SchedulePlan:
    anchor_date: date | None = None
    anchor_time: time | None = None
    enabled: bool = True
    timezone: str = "Europe/Istanbul"

    def to_dict(self) -> dict:
        return {
            "anchor_date": self.anchor_date.isoformat() if self.anchor_date else None,
            "anchor_time": self.anchor_time.isoformat() if self.anchor_time else None,
            "enabled": self.enabled,
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class YayinZamani:
    id: int
    kind: str
    due_at: datetime
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class YayinIncelemesi:
    id: int
    occurrence_id: int
    package_folder: str
    revision_digest: str
    caption: str | None
    status: str
    created_at: datetime
    version: int = 1
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    oneoff_occurrence_id: int | None = None
    last_reminded_at: datetime | None = None


@dataclass(frozen=True)
class SkipResult:
    review: YayinIncelemesi
    next_regular_at: datetime | None


@dataclass(frozen=True)
class ReminderPolicy:
    interval_minutes: int = 360
    delivery_start: time = time(8, 0)
    delivery_end: time = time(22, 0)
    timezone: str = "Europe/Istanbul"


@dataclass(frozen=True)
class PushRegistration:
    client_id: int
    token: str
    updated_at: datetime


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    data: dict[str, str]


@dataclass(frozen=True)
class NotificationResult:
    delivered: list[str]
    invalid_tokens: list[str]
    transient_failures: list[str]


REVIEW_REQUIRED_TITLE = "Yayın İncelemesi Bekliyor"
REVIEW_REQUIRED_BODY = "Paketiniz incelemeyi bekliyor. Lütfen onaylayın, atlayın veya yeniden planlayın."
