from __future__ import annotations

import json
from pathlib import Path

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.exceptions import ActivePackageExists
from dojo.model import PACKAGE_FOLDER_FORMAT, AuditEvent, Manifest, Package
from dojo.ports import AuditStore, Clock, MetaPublisher, Notifier, PackageStore, SignedUrlStore


class DojoPublishing:
    """Deep behavioral seam for the Dojo Paylaşım Paketi lifecycle.

    Consumed by both FastAPI routes and the worker scheduler. Domain rules
    live behind this facade; only the wall clock, Meta publishing,
    notifications, and signed-URL delivery are swappable adapters.
    """

    def __init__(
        self,
        *,
        packages: PackageStore,
        audit: AuditStore,
        media_root: Path,
        clock: Clock | None = None,
        meta: MetaPublisher | None = None,
        notifier: Notifier | None = None,
        signed_urls: SignedUrlStore | None = None,
    ) -> None:
        self._packages = packages
        self._audit = audit
        self.media_root = Path(media_root)
        self._clock = clock or SystemClock()
        self._meta = meta or StubMetaPublisher()
        self._notifier = notifier or StubNotifier()
        self._signed_urls = signed_urls or StubSignedUrlStore()

    def ensure_active_package(self, *, requester: str | None = None) -> Package:
        """Create an active Dojo Paylaşım Paketi when none exists."""
        existing = self._packages.get_active()
        if existing is not None:
            raise ActivePackageExists(f"active package {existing.folder_name} already exists")

        now = self._clock.now().astimezone(ISTANBUL)
        folder_name = now.strftime(PACKAGE_FOLDER_FORMAT)
        folder = self.media_root / folder_name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "manifest.json").write_text(
            json.dumps(Manifest().to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        package = self._packages.create(
            Package(id=0, folder_name=folder_name, created_at=now, status="active")
        )
        self._audit.append(
            AuditEvent(
                action="package.created",
                actor=requester or "system",
                occurred_at=now,
                details={"folder_name": folder_name},
            )
        )
        return package

    def get_active_package(self) -> Package | None:
        """Return the current active package, if any."""
        return self._packages.get_active()

    def evaluate_due_work(self) -> None:
        """Scheduler trigger; no due-work emission in the foundation ticket."""
        return None

    def list_audit(self, limit: int = 50) -> list[AuditEvent]:
        return self._audit.list_recent(limit=limit)

    def add_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def resolve_conflict(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def remove_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def restore_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def set_order(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def set_caption(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def set_branding(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def create_review(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def approve(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def skip(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def reschedule(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def render_preview(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def publish(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError
