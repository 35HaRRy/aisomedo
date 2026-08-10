from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
    caption: str | None = None
    branding: dict = field(default_factory=dict)
    render_revision: str | None = None

    def to_dict(self) -> dict:
        return {
            "media": self.media,
            "order": self.order,
            "caption": self.caption,
            "branding": self.branding,
            "render_revision": self.render_revision,
        }


@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor: str
    occurred_at: datetime
    details: dict = field(default_factory=dict)


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
