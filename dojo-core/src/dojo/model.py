from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PACKAGE_FOLDER_FORMAT = "%d-%m-%Y %H-%M"


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


@dataclass(frozen=True)
class UploadStatus:
    upload_id: str
    received_bytes: int
    declared_size_bytes: int
    status: str
    received_ranges: list[list[int]]
    error_reason: str | None = None


@dataclass(frozen=True)
class Job:
    id: int
    job_id: str
    upload_id: int
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
