from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.exceptions import (
    ActivePackageExists,
    NoActivePackage,
    PackageLimitExceeded,
    UploadChecksumMismatch,
    UploadConflict,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from dojo.model import (
    PACKAGE_FOLDER_FORMAT,
    AuditEvent,
    Job,
    Manifest,
    Package,
    Upload,
    UploadLimits,
    UploadStatus,
)
from dojo.ports import (
    AuditStore,
    Clock,
    JobStore,
    MediaProcessor,
    MetaPublisher,
    Notifier,
    PackageStore,
    SettingsStore,
    SignedUrlStore,
    UploadStore,
)

DEFAULT_MAX_FILE_BYTES = 2 * 1024**3
DEFAULT_MAX_PACKAGE_BYTES = 20 * 1024**3
STALE_TTL = timedelta(hours=24)


def merge_ranges(existing: list[list[int]], new_start: int, new_end: int) -> list[list[int]]:
    """Merge [new_start, new_end) into a sorted list of disjoint [start, end) ranges."""
    merged: list[list[int]] = []
    for start, end in existing:
        if end < new_start or new_end < start:
            merged.append([start, end])
        else:
            new_start = min(new_start, start)
            new_end = max(new_end, end)
    merged.append([new_start, new_end])
    merged.sort()
    return merged


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
        uploads: UploadStore | None = None,
        jobs: JobStore | None = None,
        settings: SettingsStore | None = None,
        media: MediaProcessor | None = None,
    ) -> None:
        self._packages = packages
        self._audit = audit
        self.media_root = Path(media_root)
        self._clock = clock or SystemClock()
        self._meta = meta or StubMetaPublisher()
        self._notifier = notifier or StubNotifier()
        self._signed_urls = signed_urls or StubSignedUrlStore()
        self._uploads: UploadStore = (
            uploads if uploads is not None else cast(UploadStore, packages)
        )
        self._jobs: JobStore = jobs if jobs is not None else cast(JobStore, packages)
        self._settings: SettingsStore = (
            settings if settings is not None else cast(SettingsStore, packages)
        )
        self._media = media

    def ensure_active_package(self, *, requester: str | None = None) -> Package:
        """Create an active Dojo Paylaşım Paketi; raise if one already exists."""
        existing = self._packages.get_active()
        if existing is not None:
            raise ActivePackageExists(f"active package {existing.folder_name} already exists")
        return self._create_active_package(requester=requester)

    def get_or_create_active_package(self, *, requester: str | None = None) -> Package:
        """Return the active package, creating it when none exists."""
        existing = self._packages.get_active()
        if existing is not None:
            return existing
        return self._create_active_package(requester=requester)

    def _create_active_package(self, *, requester: str | None = None) -> Package:
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

    def complete_active_package(self, *, requester: str | None = None) -> Package:
        """Complete the active package and create the next empty active package."""
        existing = self._packages.get_active()
        if existing is None:
            raise NoActivePackage("no active package to complete")

        now = self._clock.now().astimezone(ISTANBUL)
        completed_folder_name = f"{existing.folder_name}-completed"

        self._packages.update(replace(existing, status="completed"))
        (self.media_root / existing.folder_name).rename(
            self.media_root / completed_folder_name
        )
        self._packages.update(
            replace(existing, status="completed", folder_name=completed_folder_name)
        )

        self._audit.append(
            AuditEvent(
                action="package.completed",
                actor=requester or "system",
                occurred_at=now,
                details={"folder_name": completed_folder_name},
            )
        )
        return self._create_active_package(requester=requester)

    def get_active_package(self) -> Package | None:
        """Return the current active package, if any."""
        return self._packages.get_active()

    def get_upload_limits(self) -> UploadLimits:
        max_file = self._settings.get("upload.max_file_bytes") or DEFAULT_MAX_FILE_BYTES
        max_package = self._settings.get("upload.max_package_bytes") or DEFAULT_MAX_PACKAGE_BYTES
        return UploadLimits(
            max_file_bytes=int(cast(int, max_file)),
            max_package_bytes=int(cast(int, max_package)),
        )

    def start_upload(
        self,
        filename: str,
        content_type: str,
        declared_size_bytes: int,
        requester: str | None = None,
    ) -> UploadStatus:
        if not filename or any(c in filename for c in ("/", "\\")) or any(
            ord(c) < 32 for c in filename
        ):
            raise UploadInvalidFilename(f"unsafe filename: {filename!r}")
        limits = self.get_upload_limits()
        if declared_size_bytes > limits.max_file_bytes:
            raise UploadTooLarge(
                f"file {declared_size_bytes} bytes exceeds limit {limits.max_file_bytes}"
            )
        package = self.get_or_create_active_package(requester=requester)
        used = self._package_used_bytes(package)
        in_flight = sum(
            u.declared_size_bytes for u in self._uploads.list_active()
            if u.package_id == package.id
        )
        if used + in_flight + declared_size_bytes > limits.max_package_bytes:
            raise PackageLimitExceeded(
                f"package limit {limits.max_package_bytes} would be exceeded"
            )
        now = self._clock.now()
        upload_id = uuid.uuid4().hex
        staging = self.media_root / "tmp" / upload_id
        staging.mkdir(parents=True, exist_ok=True)
        upload = self._uploads.create(
            Upload(
                id=0,
                upload_id=upload_id,
                package_id=package.id,
                filename=filename,
                content_type=content_type,
                declared_size_bytes=declared_size_bytes,
                received_ranges=[],
                received_bytes=0,
                status="receiving",
                created_at=now,
                updated_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="upload.started",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "upload_id": upload_id,
                    "filename": filename,
                    "content_type": content_type,
                    "declared_size_bytes": declared_size_bytes,
                },
            )
        )
        return self._status(upload)

    def append_upload_range(
        self,
        upload_id: str,
        offset: int,
        length: int,
        checksum_sha256: str,
        data: bytes,
    ) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status != "receiving":
            raise UploadNotReceiving(f"upload {upload_id} is {upload.status}")
        if offset < 0 or offset + length > upload.declared_size_bytes:
            raise UploadConflict(
                f"range [{offset}, {offset + length}) exceeds declared size"
            )
        actual = hashlib.sha256(data).hexdigest()
        if actual != checksum_sha256:
            raise UploadChecksumMismatch(
                f"checksum mismatch for upload {upload_id}: got {actual[:8]}"
            )
        staged = self.media_root / "tmp" / upload_id / "original"
        staged.touch()
        with staged.open("r+b") as fh:
            fh.seek(offset)
            fh.write(data)
        now = self._clock.now()
        ranges = merge_ranges(upload.received_ranges, offset, offset + length)
        received = sum(end - start for start, end in ranges)
        updated = self._uploads.update(
            replace(upload, received_ranges=ranges, received_bytes=received, updated_at=now)
        )
        return self._status(updated)

    def get_upload_status(self, upload_id: str) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        return self._status(upload)

    def list_active_uploads(self) -> list[UploadStatus]:
        return [self._status(u) for u in self._uploads.list_active()]

    def complete_upload(
        self, upload_id: str, requester: str | None = None
    ) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status != "receiving":
            raise UploadConflict(f"upload {upload_id} is {upload.status}")
        if upload.received_bytes < upload.declared_size_bytes:
            raise UploadIncomplete(
                f"upload {upload_id} has {upload.received_bytes} of "
                f"{upload.declared_size_bytes} bytes"
            )
        now = self._clock.now()
        queued = self._uploads.update(
            replace(upload, status="queued", updated_at=now)
        )
        self._jobs.create(
            Job(
                id=0,
                job_id=uuid.uuid4().hex,
                upload_id=queued.id,
                kind="media.process",
                status="queued",
                payload={"upload_id": upload_id},
                created_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="upload.completed",
                actor=requester or "system",
                occurred_at=now,
                details={"upload_id": upload_id, "filename": upload.filename},
            )
        )
        return self._status(queued)

    def abort_upload(self, upload_id: str, requester: str | None = None) -> None:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status == "finalized":
            raise UploadConflict(f"upload {upload_id} is finalized")
        now = self._clock.now()
        self._uploads.update(replace(upload, status="aborted", updated_at=now))
        staging = self.media_root / "tmp" / upload_id
        import shutil

        shutil.rmtree(staging, ignore_errors=True)
        self._audit.append(
            AuditEvent(
                action="upload.aborted",
                actor=requester or "system",
                occurred_at=now,
                details={"upload_id": upload_id},
            )
        )

    def _package_used_bytes(self, package: Package) -> int:
        manifest_path = self.media_root / package.folder_name / "manifest.json"
        if not manifest_path.is_file():
            return 0
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return sum(int(entry.get("size_bytes", 0)) for entry in manifest.get("media", []))

    @staticmethod
    def _status(upload: Upload) -> UploadStatus:
        return UploadStatus(
            upload_id=upload.upload_id,
            received_bytes=upload.received_bytes,
            declared_size_bytes=upload.declared_size_bytes,
            status=upload.status,
            received_ranges=upload.received_ranges,
        )

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
