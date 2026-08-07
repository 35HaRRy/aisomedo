from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from dojo.model import AuditEvent, Package


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class PackageStore(Protocol):
    def create(self, package: Package) -> Package: ...
    def get_active(self) -> Package | None: ...


@runtime_checkable
class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list_recent(self, limit: int = 50) -> list[AuditEvent]: ...


@runtime_checkable
class MetaPublisher(Protocol):
    def publish_reel(self, signed_url: str, caption: str) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


@runtime_checkable
class SignedUrlStore(Protocol):
    def create(self, artifact_path: Path) -> str: ...
    def revoke(self, url: str) -> None: ...
