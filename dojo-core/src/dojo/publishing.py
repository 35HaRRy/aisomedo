from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import cast

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.exceptions import (
    ActivePackageExists,
    JobNotFound,
    LogoNotConfigured,
    ManualPublishConflict,
    MediaNotFound,
    MediaNotRemovable,
    MediaNotRestorable,
    MediaValidationError,
    MontageDurationExceeded,
    MontageOrderInvalid,
    MontageTrimInvalid,
    NoActivePackage,
    PackageCompleted,
    PackageLimitExceeded,
    PlanInvalid,
    RenderFailed,
    UploadChecksumMismatch,
    UploadConflict,
    UploadDecisionInvalid,
    UploadIncomplete,
    UploadInvalidFilename,
    UploadNotFound,
    UploadNotReceiving,
    UploadTooLarge,
)
from dojo.model import (
    CONFLICT_DECISIONS,
    KEEP_BOTH,
    KEEP_SELECTED,
    KEEP_TARGET,
    PACKAGE_FOLDER_FORMAT,
    AuditEvent,
    BrandingConfig,
    Job,
    Manifest,
    MediaEntry,
    MontageClip,
    MontageLimits,
    MontageStatus,
    Package,
    ProcessedMedia,
    ReelBuild,
    ReelClip,
    SchedulePlan,
    Upload,
    UploadLimits,
    UploadStatus,
    YayinIncelemesi,
    YayinZamani,
)
from dojo.ports import (
    AuditStore,
    Clock,
    JobStore,
    MediaProcessor,
    MetaPublisher,
    Notifier,
    PackageStore,
    ReelRenderer,
    ReviewStore,
    ScheduleStore,
    SettingsStore,
    SignedUrlStore,
    UploadStore,
)

DEFAULT_MAX_FILE_BYTES = 2 * 1024**3
DEFAULT_MAX_PACKAGE_BYTES = 20 * 1024**3
STALE_TTL = timedelta(hours=24)

DEFAULT_MAX_MONTAGE_SECONDS = 90.0
DEFAULT_PHOTO_SECONDS = 3.0


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


def _ext_for(content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
    }
    return mapping.get(content_type, "")


def _normalize(filename: str) -> str:
    """Portable case-insensitive key for a display filename (Unicode-safe)."""
    return filename.casefold()


def _first_free_suffixed_name(
    media: list[dict], stem: str, ext: str, *, start: int = 1
) -> str:
    """Return the first free ``stem (N)ext`` not already used by ``media``."""
    taken = {_normalize(str(entry.get("filename", ""))) for entry in media}
    n = start
    while True:
        candidate = f"{stem} ({n}){ext}"
        if _normalize(candidate) not in taken:
            return candidate
        n += 1


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
        renderer: ReelRenderer | None = None,
        schedule: ScheduleStore | None = None,
        reviews: ReviewStore | None = None,
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
        self._schedule: ScheduleStore = (
            schedule if schedule is not None else cast(ScheduleStore, packages)
        )
        self._reviews: ReviewStore = (
            reviews if reviews is not None else cast(ReviewStore, packages)
        )
        self._media = media
        self._renderer = renderer

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
        self._seed_draft_defaults(package)
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
        targets = self._manifest_collisions(package, filename)
        now = self._clock.now()
        if targets:
            upload_id = uuid.uuid4().hex
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
                    status="conflict",
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
                        "conflict": True,
                    },
                )
            )
            return self._status(upload)
        self._assert_package_capacity(package, declared_size_bytes)
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
        statuses = [self._status(u) for u in self._uploads.list_active()]
        package = self._packages.get_active()
        if package is not None:
            statuses.extend(
                self._status(u) for u in self._uploads.list_conflicts(package.id)
            )
        return statuses

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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return sum(int(entry.get("size_bytes", 0)) for entry in manifest.get("media", []))

    def _manifest_media(self, package: Package) -> list[dict]:
        manifest_path = self.media_root / package.folder_name / "manifest.json"
        if not manifest_path.is_file():
            return []
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest.get("media", [])

    def _manifest_collisions(self, package: Package, filename: str) -> list[dict]:
        """Finalized manifest entries whose normalized name matches ``filename``."""
        key = _normalize(filename)
        return [
            entry
            for entry in self._manifest_media(package)
            if entry.get("status") == "finalized"
            and _normalize(str(entry.get("filename", ""))) == key
        ]

    def _assert_package_capacity(
        self, package: Package, additional_bytes: int
    ) -> None:
        used = self._package_used_bytes(package)
        in_flight = sum(
            u.declared_size_bytes
            for u in self._uploads.list_active()
            if u.package_id == package.id
        )
        limits = self.get_upload_limits()
        if used + in_flight + additional_bytes > limits.max_package_bytes:
            raise PackageLimitExceeded(
                f"package limit {limits.max_package_bytes} would be exceeded"
            )

    def _status(self, upload: Upload) -> UploadStatus:
        conflicts: list[dict] = []
        if upload.status == "conflict":
            package = self._packages.get_active()
            if package is not None:
                conflicts = self._manifest_collisions(package, upload.filename)
        return UploadStatus(
            upload_id=upload.upload_id,
            received_bytes=upload.received_bytes,
            declared_size_bytes=upload.declared_size_bytes,
            status=upload.status,
            received_ranges=upload.received_ranges,
            error_reason=upload.error_reason,
            conflicts=conflicts,
        )

    def claim_next_job(self) -> Job | None:
        return self._jobs.claim_next(self._clock.now())

    def process_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(f"job {job_id} not found")
        if job.status != "processing":
            raise UploadConflict(f"job {job_id} is {job.status}")
        if job.kind == "render":
            self._process_render_job(job)
            return
        upload = self._uploads.get_by_pk(job.upload_id)
        if upload is None:
            self._fail_job(job, "upload missing")
            return
        now = self._clock.now()
        self._uploads.update(replace(upload, status="processing", updated_at=now))
        original = self.media_root / "tmp" / upload.upload_id / "original"
        if not original.is_file():
            self._fail_job(job, "staged original missing")
            return
        try:
            processor = self._media
            if processor is None:
                from dojo.adapters.media import PillowFFmpegProcessor

                processor = PillowFFmpegProcessor()
            processed = processor.process(
                upload, original, self.media_root / "tmp" / upload.upload_id
            )
        except MediaValidationError as exc:
            self._fail_job(job, str(exc))
            return
        self.finalize_media(job.job_id, processed)

    def finalize_media(self, job_id: str, processed: ProcessedMedia) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(f"job {job_id} not found")
        upload = self._uploads.get_by_pk(job.upload_id)
        if upload is None or upload.status != "processing":
            raise UploadConflict(f"upload for job {job_id} is not processing")
        required = upload.declared_size_bytes + processed.size_bytes
        free = shutil.disk_usage(self.media_root).free
        if free < required:
            self._fail_job(job, f"insufficient disk space: {free} free, {required} needed")
            return
        package = self._packages.get_active()
        if package is None:
            self._fail_job(job, "no active package")
            return
        now = self._clock.now()
        media_id = uuid.uuid4().hex
        media_dir = self.media_root / package.folder_name / "media" / media_id
        media_dir.mkdir(parents=True, exist_ok=True)
        original_ext = Path(upload.filename).suffix or _ext_for(upload.content_type)
        processed_ext = _ext_for(processed.content_type)
        original_dst = media_dir / f"original{original_ext}"
        processed_dst = media_dir / f"processed{processed_ext}"
        shutil.move(str(processed.original_path), str(original_dst))
        shutil.move(str(processed.processed_path), str(processed_dst))

        manifest_path = self.media_root / package.folder_name / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["render_revision"] = None
        display_name = upload.filename
        overwrite_target: str | None = None
        if upload.conflict_decision == KEEP_BOTH:
            display_name = _first_free_suffixed_name(
                manifest.get("media", []),
                Path(upload.filename).stem,
                Path(upload.filename).suffix,
            )
        elif (
            upload.conflict_decision == KEEP_SELECTED
            and upload.conflict_target_media_id
        ):
            overwrite_target = upload.conflict_target_media_id
            manifest["media"] = [
                entry
                for entry in manifest.get("media", [])
                if entry.get("media_id") != overwrite_target
            ]
            manifest["order"] = [
                mid for mid in manifest.get("order", []) if mid != overwrite_target
            ]
            shutil.rmtree(
                self.media_root / package.folder_name / "media" / overwrite_target,
                ignore_errors=True,
            )

        entry = MediaEntry(
            media_id=media_id,
            filename=display_name,
            content_type=upload.content_type,
            size_bytes=upload.declared_size_bytes,
            uploaded_at=upload.created_at,
            status="finalized",
            processed={
                "path": f"media/{media_id}/processed{processed_ext}",
                "content_type": processed.content_type,
                "size_bytes": processed.size_bytes,
                **(
                    {"duration": processed.duration}
                    if processed.duration is not None
                    else {}
                ),
            },
        ).to_dict()

        manifest.setdefault("media", []).append(entry)
        manifest.setdefault("order", []).append(media_id)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        self._uploads.update(replace(upload, status="finalized", updated_at=now))
        self._jobs.update(
            replace(job, status="done", finished_at=now, error_reason=None)
        )
        staging = self.media_root / "tmp" / upload.upload_id
        shutil.rmtree(staging, ignore_errors=True)
        self._audit.append(
            AuditEvent(
                action="media.finalized",
                actor="worker",
                occurred_at=now,
                details={
                    "media_id": media_id,
                    "upload_id": upload.upload_id,
                    "filename": display_name,
                    "package": package.folder_name,
                },
            )
        )
        if overwrite_target is not None:
            self._audit.append(
                AuditEvent(
                    action="media.overwritten",
                    actor="worker",
                    occurred_at=now,
                    details={
                        "target_media_id": overwrite_target,
                        "media_id": media_id,
                        "filename": display_name,
                        "package": package.folder_name,
                    },
                )
            )

    def sweep_stale_uploads(self, ttl: timedelta = STALE_TTL) -> int:
        cutoff = self._clock.now() - ttl
        stale = self._uploads.list_stale(cutoff)
        for upload in stale:
            now = self._clock.now()
            self._uploads.update(replace(upload, status="aborted", updated_at=now))
            shutil.rmtree(self.media_root / "tmp" / upload.upload_id, ignore_errors=True)
            self._audit.append(
                AuditEvent(
                    action="upload.expired",
                    actor="worker",
                    occurred_at=now,
                    details={"upload_id": upload.upload_id},
                )
            )
        return len(stale)

    def _process_render_job(self, job: Job) -> None:
        payload = job.payload or {}
        try:
            self._render_job(job, str(payload.get("package", "")))
        except RenderFailed as exc:
            now = self._clock.now()
            self._fail_job(job, str(exc))
            self._audit.append(
                AuditEvent(
                    action="render.rejected",
                    actor="worker",
                    occurred_at=now,
                    details={"job_id": job.job_id, "reason": str(exc)},
                )
            )
            self._record_render_failure(job, payload)
            return
        now = self._clock.now()
        self._jobs.update(
            replace(job, status="done", finished_at=now, error_reason=None)
        )

    def _fail_job(self, job: Job, reason: str) -> None:
        upload = self._uploads.get_by_pk(job.upload_id)
        now = self._clock.now()
        if upload is not None:
            self._uploads.update(
                replace(upload, status="failed", error_reason=reason, updated_at=now)
            )
        self._jobs.update(
            replace(job, status="failed", error_reason=reason, finished_at=now)
        )
        if upload is not None:
            shutil.rmtree(self.media_root / "tmp" / upload.upload_id, ignore_errors=True)
        self._audit.append(
            AuditEvent(
                action="upload.rejected",
                actor="worker",
                occurred_at=now,
                details={"job_id": job.job_id, "reason": reason},
            )
        )

    def _render_failed_digest(self, package: Package) -> str | None:
        try:
            manifest = self._load_manifest(package)
        except MediaNotFound:
            return None
        return manifest.get("recovery", {}).get("render_failed_digest")

    def _record_render_failure(self, job: Job, payload: dict) -> None:
        package: Package | None = None
        package_folder = str(payload.get("package", ""))
        for candidate in [self._packages.get_active(), *self._packages.list_completed()]:
            if candidate is not None and candidate.folder_name == package_folder:
                package = candidate
                break
        if package is None:
            return
        manifest = self._load_manifest(package)
        manifest.setdefault("recovery", {})["render_failed_digest"] = self._render_digest(
            package, manifest
        )
        self._write_manifest(package, manifest)
        shutil.rmtree(self.media_root / "tmp" / f"render-{job.job_id}", ignore_errors=True)

    def evaluate_due_work(self) -> None:
        """Scheduler trigger: materialize due slots, then create durable reviews."""
        self.ensure_schedule_upto()
        self._ensure_reviews_for_due()

    def _ensure_reviews_for_due(self) -> None:
        """Create at most one durable review per due occurrence for the active revision.

        A review is only created once a render is materialized. For a non-empty package
        we enqueue a render when stale (the render job's completion hook creates the
        review) or, when the render is already current, create it directly. An empty
        active package creates no review and leaves the occurrence pending.
        """
        package = self._packages.get_active()
        if package is None:
            return
        manifest = self._load_manifest(package)
        if not self._finalized_in_order(manifest):
            return
        digest = self._render_digest(package, manifest)
        if manifest.get("render_revision") == digest:
            self._create_review_if_due(package, digest)
        else:
            self._enqueue_render(package, digest)

    def _create_review_if_due(self, package: Package, digest: str) -> None:
        """Create a durable review for each due pending occurrence lacking one.

        Idempotent: a review already recorded for ``(occurrence_id, revision_digest)``
        is never duplicated, so scheduler re-runs and restarts add nothing.
        """
        due = self._schedule.list_due(self._clock.now())
        if not due:
            return
        manifest = self._load_manifest(package)
        caption = manifest.get("caption")
        now = self._clock.now()
        for occurrence in due:
            if (
                self._reviews.get_by_occurrence_revision(occurrence.id, digest)
                is not None
            ):
                continue
            review = self._reviews.create(
                YayinIncelemesi(
                    id=0,
                    occurrence_id=occurrence.id,
                    package_folder=package.folder_name,
                    revision_digest=digest,
                    caption=caption,
                    status="pending",
                    created_at=now,
                )
            )
            self._audit.append(
                AuditEvent(
                    action="review.created",
                    actor="worker",
                    occurred_at=now,
                    details={
                        "review_id": review.id,
                        "occurrence_id": occurrence.id,
                        "package": package.folder_name,
                        "revision_digest": digest,
                    },
                )
            )

    def list_pending_reviews(self) -> list[YayinIncelemesi]:
        return self._reviews.list_pending()

    def list_audit(self, limit: int = 50) -> list[AuditEvent]:
        return self._audit.list_recent(limit=limit)

    def add_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def resolve_conflict(
        self,
        upload_id: str,
        decision: str,
        target_media_id: str | None = None,
        apply_to_all: bool = False,
        confirmed_overwrite: bool = False,
        requester: str | None = None,
    ) -> UploadStatus:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound(f"upload {upload_id} not found")
        if upload.status != "conflict":
            raise UploadConflict(f"upload {upload_id} is {upload.status}")
        if decision not in CONFLICT_DECISIONS:
            raise UploadDecisionInvalid(f"unknown conflict decision {decision!r}")
        package = self._packages.get_active()
        if package is None:
            raise UploadConflict("no active package to resolve against")
        now = self._clock.now()
        if decision == KEEP_TARGET:
            return self._resolve_keep_target(
                upload, package, apply_to_all=apply_to_all, now=now, requester=requester
            )
        if decision == KEEP_SELECTED:
            if not confirmed_overwrite:
                raise UploadDecisionInvalid(
                    "keep_selected is a destructive overwrite; pass confirmed_overwrite=True"
                )
            targets = self._manifest_collisions(package, upload.filename)
            if not target_media_id or target_media_id not in {
                t["media_id"] for t in targets
            }:
                raise UploadConflict(
                    f"target_media_id {target_media_id!r} is not a colliding finalized target"
                )
        return self._resolve_to_receiving(
            upload,
            package,
            decision,
            target_media_id=target_media_id,
            apply_to_all=apply_to_all,
            now=now,
            requester=requester,
        )

    def _resolve_keep_target(
        self,
        upload: Upload,
        package: Package,
        *,
        apply_to_all: bool,
        now: datetime,
        requester: str | None,
    ) -> UploadStatus:
        def transition(candidate: Upload) -> Upload:
            return self._uploads.update(
                replace(candidate, status="aborted", updated_at=now)
            )

        return self._resolve_candidates(
            upload,
            package,
            decision=KEEP_TARGET,
            apply_to_all=apply_to_all,
            now=now,
            requester=requester,
            transition=transition,
        )

    def _resolve_to_receiving(
        self,
        upload: Upload,
        package: Package,
        decision: str,
        *,
        target_media_id: str | None,
        apply_to_all: bool,
        now: datetime,
        requester: str | None,
    ) -> UploadStatus:
        def transition(candidate: Upload) -> Upload:
            cand_target: str | None = None
            if decision == KEEP_SELECTED:
                if apply_to_all:
                    targets = self._manifest_collisions(package, candidate.filename)
                    cand_target = targets[0]["media_id"] if targets else None
                else:
                    cand_target = target_media_id
            self._assert_package_capacity(package, candidate.declared_size_bytes)
            staging = self.media_root / "tmp" / candidate.upload_id
            staging.mkdir(parents=True, exist_ok=True)
            return self._uploads.update(
                replace(
                    candidate,
                    status="receiving",
                    conflict_decision=decision,
                    conflict_target_media_id=cand_target,
                    updated_at=now,
                )
            )

        return self._resolve_candidates(
            upload,
            package,
            decision=decision,
            apply_to_all=apply_to_all,
            now=now,
            requester=requester,
            transition=transition,
        )

    def _resolve_candidates(
        self,
        upload: Upload,
        package: Package,
        *,
        decision: str,
        apply_to_all: bool,
        now: datetime,
        requester: str | None,
        transition: Callable[[Upload], Upload],
    ) -> UploadStatus:
        """Apply one resolution to the triggering upload (or all compatible conflicts)."""
        candidates = self._conflict_uploads(package, upload, apply_to_all=apply_to_all)
        last = upload
        for candidate in candidates:
            updated = transition(candidate)
            self._audit.append(
                AuditEvent(
                    action="conflict.resolved",
                    actor=requester or "system",
                    occurred_at=now,
                    details={
                        "upload_id": candidate.upload_id,
                        "decision": updated.conflict_decision or decision,
                        "target_media_id": updated.conflict_target_media_id,
                        "apply_to_all": apply_to_all,
                        "filename": candidate.filename,
                    },
                )
            )
            last = updated
        return self._status(last)

    def _conflict_uploads(
        self, package: Package, upload: Upload, *, apply_to_all: bool
    ) -> list[Upload]:
        """The triggering upload, or all compatible conflicts when applying to all."""
        if not apply_to_all:
            return [upload]
        key = _normalize(upload.filename)
        return [
            candidate
            for candidate in self._uploads.list_conflicts(package.id)
            if _normalize(candidate.filename) == key
        ]

    def remove_media(self, media_id: str, requester: str | None = None) -> None:
        """Exclude ``media_id`` from the active montage without deleting its file.

        The media dir moves to package-local ``removed/`` storage, the manifest
        entry status becomes ``removed``, and the id leaves ``order``. The source
        file is never deleted and may be restored while the package is active.
        """
        self._toggle_media(
            media_id,
            from_status="finalized",
            to_status="removed",
            action="media.removed",
            requester=requester,
        )

    def restore_media(self, media_id: str, requester: str | None = None) -> None:
        """Return removed ``media_id`` to the active montage."""
        self._toggle_media(
            media_id,
            from_status="removed",
            to_status="finalized",
            action="media.restored",
            requester=requester,
        )

    def _toggle_media(
        self,
        media_id: str,
        *,
        from_status: str,
        to_status: str,
        action: str,
        requester: str | None,
    ) -> None:
        package = self._require_active_package()
        if self._media_in_completed(media_id):
            raise PackageCompleted(f"media {media_id} belongs to a completed package")
        manifest = self._load_manifest(package)
        entry = next((e for e in manifest.get("media", []) if e.get("media_id") == media_id), None)
        if entry is None:
            raise MediaNotFound(f"media {media_id} not found in active package")
        if entry.get("status") != from_status:
            if from_status == "finalized":
                raise MediaNotRemovable(f"media {media_id} is {entry.get('status')}")
            raise MediaNotRestorable(f"media {media_id} is {entry.get('status')}")

        src = self.media_root / package.folder_name / (
            "media" if from_status == "finalized" else "removed"
        ) / media_id
        dst = self.media_root / package.folder_name / (
            "removed" if from_status == "finalized" else "media"
        ) / media_id
        if not src.is_dir():
            raise MediaNotFound(f"{'media' if from_status == 'finalized' else 'removed'} "
                                f"storage for media {media_id} missing")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

        if from_status == "finalized":
            order = manifest.get("order", [])
            entry["removed_position"] = order.index(media_id) if media_id in order else len(order)
            entry["status"] = "removed"
            manifest["order"] = [mid for mid in order if mid != media_id]
        else:
            entry["status"] = "finalized"
            position = int(entry.pop("removed_position", len(manifest.get("order", []))))
            order = manifest.get("order", [])
            order.insert(min(position, len(order)), media_id)
            manifest["order"] = order
        self._write_manifest(package, manifest)

        now = self._clock.now()
        self._audit.append(
            AuditEvent(
                action=action,
                actor=requester or "system",
                occurred_at=now,
                details={"media_id": media_id, "package": package.folder_name},
            )
        )

    def _require_active_package(self) -> Package:
        package = self._packages.get_active()
        if package is None:
            raise NoActivePackage("no active package to mutate")
        return package

    def list_completed_packages(self) -> list[Package]:
        """Return completed packages (read-only historical packages)."""
        return self._packages.list_completed()

    def browse_completed_package(self, folder_name: str) -> dict:
        """Return a read-only manifest view of a completed package."""
        package = self._get_completed_package(folder_name)
        manifest = self._load_manifest(package)
        return {
            "folder_name": package.folder_name,
            "media": manifest.get("media", []),
            "order": manifest.get("order", []),
            "caption": manifest.get("caption"),
            "render_revision": manifest.get("render_revision"),
        }

    def create_download_url(self, folder_name: str, artifact_ref: str) -> str:
        """Resolve ``artifact_ref`` under a completed package and return a signed URL."""
        package = self._get_completed_package(folder_name)
        root = (self.media_root / package.folder_name).resolve()
        candidate = (root / artifact_ref).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"artifact_ref {artifact_ref!r} escapes package") from exc
        if not candidate.is_file():
            raise MediaNotFound(f"artifact {artifact_ref!r} not found")
        return self._signed_urls.create(candidate)

    def _get_completed_package(self, folder_name: str) -> Package:
        for package in self._packages.list_completed():
            if package.folder_name == folder_name:
                return package
        raise MediaNotFound(f"completed package {folder_name!r} not found")

    def _media_in_completed(self, media_id: str) -> bool:
        for package in self._packages.list_completed():
            if any(
                e.get("media_id") == media_id
                for e in self._load_manifest(package).get("media", [])
            ):
                return True
        return False

    def _load_manifest(self, package: Package) -> dict:
        manifest_path = self.media_root / package.folder_name / "manifest.json"
        if not manifest_path.is_file():
            raise MediaNotFound(f"manifest for {package.folder_name} missing")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _write_manifest(self, package: Package, manifest: dict) -> None:
        manifest_path = self.media_root / package.folder_name / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_plan(self) -> SchedulePlan:
        enabled = self._settings.get("schedule.enabled")
        anchor_date_raw = self._settings.get("schedule.anchor_date")
        anchor_time_raw = self._settings.get("schedule.anchor_time")
        anchor_date = None
        anchor_time = None
        if isinstance(anchor_date_raw, str) and anchor_date_raw:
            anchor_date = date.fromisoformat(anchor_date_raw)
        if isinstance(anchor_time_raw, str) and anchor_time_raw:
            anchor_time = time.fromisoformat(anchor_time_raw)
        return SchedulePlan(
            anchor_date=anchor_date,
            anchor_time=anchor_time,
            enabled=bool(enabled) if enabled is not None else False,
        )

    def set_plan(
        self, plan: SchedulePlan, requester: str | None = None
    ) -> SchedulePlan:
        if plan.anchor_date is None or plan.anchor_time is None:
            raise PlanInvalid("anchor date and time are required")
        if plan.anchor_date.weekday() != 0:
            raise PlanInvalid(f"anchor must be a Monday, got {plan.anchor_date}")
        now = self._clock.now()
        self._settings.set("schedule.enabled", plan.enabled, updated_at=now)
        self._settings.set("schedule.anchor_date", plan.anchor_date.isoformat(), updated_at=now)
        self._settings.set("schedule.anchor_time", plan.anchor_time.isoformat(), updated_at=now)
        self._audit.append(
            AuditEvent(
                action="plan.updated",
                actor=requester or "system",
                occurred_at=now,
                details=plan.to_dict(),
            )
        )
        return self.get_plan()

    def manual_publish(self, requester: str | None = None) -> YayinZamani:
        if self._schedule.has_pending_manual():
            raise ManualPublishConflict("a manual publish slot is already pending")
        now = self._clock.now().astimezone(ISTANBUL)
        occurrence = self._schedule.create(
            YayinZamani(
                id=0, kind="manual", due_at=now, status="pending", created_at=now
            )
        )
        self._audit.append(
            AuditEvent(
                action="schedule.manual_created",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "occurrence_id": occurrence.id,
                    "due_at": occurrence.due_at.isoformat(),
                },
            )
        )
        return occurrence

    def ensure_schedule_upto(self, now: datetime | None = None) -> None:
        plan = self.get_plan()
        if not plan.enabled or plan.anchor_date is None or plan.anchor_time is None:
            return
        now = (now or self._clock.now()).astimezone(ISTANBUL)
        created_now = self._clock.now().astimezone(ISTANBUL)
        anchor_dt = datetime.combine(
            plan.anchor_date, plan.anchor_time, tzinfo=ISTANBUL
        )
        self._schedule.prune_regular_future(now)
        occ_dt = anchor_dt
        while occ_dt <= now:
            if not self._schedule.has_regular_at(occ_dt):
                self._schedule.create(
                    YayinZamani(
                        id=0, kind="regular", due_at=occ_dt,
                        status="pending", created_at=created_now,
                    )
                )
            occ_dt += timedelta(days=14)
        next_dt = anchor_dt
        while next_dt <= now:
            next_dt += timedelta(days=14)
        if not self._schedule.has_regular_at(next_dt):
            self._schedule.create(
                YayinZamani(
                    id=0, kind="regular", due_at=next_dt,
                    status="pending", created_at=created_now,
                )
            )

    def list_due_occurrences(self, now: datetime | None = None) -> list[YayinZamani]:
        now = (now or self._clock.now()).astimezone(ISTANBUL)
        return self._schedule.list_due(now)

    def get_branding_defaults(self) -> BrandingConfig:
        """Return the installation-wide branding defaults (empty when unset)."""
        return BrandingConfig(
            logo_asset=cast(str | None, self._settings.get("branding.logo_asset")),
            intro_asset=cast(str | None, self._settings.get("branding.intro_asset")),
            intro_duration=cast(
                float | None, self._settings.get("branding.intro_duration")
            ),
            outro_asset=cast(str | None, self._settings.get("branding.outro_asset")),
            outro_duration=cast(
                float | None, self._settings.get("branding.outro_duration")
            ),
            caption_template=cast(
                str | None, self._settings.get("branding.caption_template")
            ),
        )

    def set_branding_defaults(
        self, config: BrandingConfig, requester: str | None = None
    ) -> BrandingConfig:
        """Set the installation-wide branding defaults; draft copies keep old values."""
        now = self._clock.now()
        for key, value in config.to_dict().items():
            self._settings.set(f"branding.{key}", value, updated_at=now)
        self._audit.append(
            AuditEvent(
                action="branding.defaults_updated",
                actor=requester or "system",
                occurred_at=now,
                details=config.to_dict(),
            )
        )
        return self.get_branding_defaults()

    def _seed_draft_defaults(self, package: Package) -> None:
        defaults = self.get_branding_defaults()
        manifest = self._load_manifest(package)
        manifest["branding"] = {
            "logo_asset": defaults.logo_asset,
            "intro_asset": defaults.intro_asset,
            "intro_duration": defaults.intro_duration,
            "outro_asset": defaults.outro_asset,
            "outro_duration": defaults.outro_duration,
        }
        if defaults.caption_template is not None:
            manifest["caption"] = defaults.caption_template
        self._write_manifest(package, manifest)

    def get_draft_branding(self) -> dict:
        package = self._require_active_package()
        return self._load_manifest(package).get("branding", {})

    def get_draft_caption(self) -> str | None:
        package = self._require_active_package()
        return self._load_manifest(package).get("caption")

    def set_branding(self, branding: dict, requester: str | None = None) -> dict:
        """Override intro/outro (and logo) for one draft without touching globals."""
        package = self._require_active_package()
        manifest = self._load_manifest(package)
        current = dict(manifest.get("branding", {}))
        current.update(branding)
        manifest["branding"] = current
        manifest["render_revision"] = None
        self._write_manifest(package, manifest)
        self._audit.append(
            AuditEvent(
                action="branding.draft_updated",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"branding": current, "package": package.folder_name},
            )
        )
        return current

    def set_caption(self, caption: str, requester: str | None = None) -> str:
        """Edit the draft caption copy without changing the global template."""
        package = self._require_active_package()
        manifest = self._load_manifest(package)
        manifest["caption"] = caption
        manifest["render_revision"] = None
        self._write_manifest(package, manifest)
        self._audit.append(
            AuditEvent(
                action="caption.draft_updated",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"package": package.folder_name},
            )
        )
        return caption

    def _assert_logo_configured(self) -> None:
        logo = self.get_branding_defaults().logo_asset
        package = self._packages.get_active()
        if package is not None:
            draft_logo = self._load_manifest(package).get("branding", {}).get("logo_asset")
            if draft_logo is not None:
                logo = draft_logo
        if logo is None:
            raise LogoNotConfigured("dojo logo watermark asset is not configured")

    def get_montage_limits(self) -> MontageLimits:
        max_seconds = (
            self._settings.get("montage.max_duration_seconds")
            or DEFAULT_MAX_MONTAGE_SECONDS
        )
        photo_seconds = (
            self._settings.get("montage.photo_duration_seconds")
            or DEFAULT_PHOTO_SECONDS
        )
        return MontageLimits(
            max_duration_seconds=float(cast(float, max_seconds)),
            photo_duration_seconds=float(cast(float, photo_seconds)),
        )

    def _clip_duration(self, entry: dict, trims: dict, photo_duration: float) -> float:
        if str(entry.get("content_type", "")).startswith("video/"):
            source = float(entry.get("processed", {}).get("duration") or 0.0)
            trim = trims.get(entry.get("media_id"))
            if trim:
                source -= float(trim["end"]) - float(trim["start"])
            return max(source, 0.0)
        return photo_duration

    def _combined_duration(self, order: list[str], trims: dict) -> float:
        limits = self.get_montage_limits()
        package = self._packages.get_active()
        if package is None:
            return 0.0
        manifest = self._load_manifest(package)
        by_id = {e.get("media_id"): e for e in manifest.get("media", [])}
        total = 0.0
        for media_id in order:
            entry = by_id.get(media_id)
            if entry is None or entry.get("status") != "finalized":
                continue
            total += self._clip_duration(entry, trims, limits.photo_duration_seconds)
        return total

    def get_montage_status(self) -> MontageStatus:
        package = self._require_active_package()
        manifest = self._load_manifest(package)
        limits = self.get_montage_limits()
        order = manifest.get("order", [])
        trims = manifest.get("trims", {})
        by_id = {e.get("media_id"): e for e in manifest.get("media", [])}
        clips: list[MontageClip] = []
        for media_id in order:
            entry = by_id.get(media_id)
            if entry is None or entry.get("status") != "finalized":
                continue
            is_video = str(entry.get("content_type", "")).startswith("video/")
            source = (
                float(entry.get("processed", {}).get("duration") or 0.0)
                if is_video else None
            )
            clips.append(
                MontageClip(
                    media_id=media_id,
                    filename=str(entry.get("filename", "")),
                    content_type=str(entry.get("content_type", "")),
                    is_video=is_video,
                    source_duration=source,
                    effective_duration=self._clip_duration(
                        entry, trims, limits.photo_duration_seconds
                    ),
                )
            )
        combined = sum(c.effective_duration for c in clips)
        over_limit = combined > limits.max_duration_seconds
        required_action = None
        if over_limit:
            excess = combined - limits.max_duration_seconds
            required_action = f"trim or remove {excess:.1f}s"
        return MontageStatus(
            order=order,
            trims=trims,
            clips=clips,
            combined_duration=combined,
            max_duration_seconds=limits.max_duration_seconds,
            over_limit=over_limit,
            required_action=required_action,
        )

    def set_order(self, order: list[str], requester: str | None = None) -> MontageStatus:
        package = self._require_active_package()
        if any(self._media_in_completed(mid) for mid in order):
            raise PackageCompleted("media belongs to a completed package")
        manifest = self._load_manifest(package)
        finalized = [
            e.get("media_id")
            for e in manifest.get("media", [])
            if e.get("status") == "finalized"
        ]
        if len(order) != len(set(order)) or set(order) != set(finalized):
            raise MontageOrderInvalid(
                "order must contain every finalized media id exactly once"
            )
        limits = self.get_montage_limits()
        combined = self._combined_duration(order, manifest.get("trims", {}))
        if combined > limits.max_duration_seconds:
            excess = combined - limits.max_duration_seconds
            raise MontageDurationExceeded(
                f"combined duration {combined:.1f}s exceeds {limits.max_duration_seconds:.1f}s "
                f"limit; trim or remove {excess:.1f}s"
            )
        manifest["order"] = list(order)
        manifest["render_revision"] = None
        self._write_manifest(package, manifest)
        self._audit.append(
            AuditEvent(
                action="montage.order_changed",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"order": list(order), "package": package.folder_name},
            )
        )
        return self.get_montage_status()

    def set_trims(self, trims: dict, requester: str | None = None) -> MontageStatus:
        package = self._require_active_package()
        if any(self._media_in_completed(mid) for mid in trims):
            raise PackageCompleted("media belongs to a completed package")
        manifest = self._load_manifest(package)
        by_id = {
            e.get("media_id"): e
            for e in manifest.get("media", [])
            if e.get("status") == "finalized"
        }
        cleaned: dict = {}
        for media_id, trim in trims.items():
            entry = by_id.get(media_id)
            if entry is None:
                raise MediaNotFound(f"media {media_id} not found in active package")
            if not str(entry.get("content_type", "")).startswith("video/"):
                raise MontageTrimInvalid(
                    f"media {media_id} is not a video; trims apply to videos only"
                )
            start = float(trim["start"])
            end = float(trim["end"])
            duration = float(entry.get("processed", {}).get("duration") or 0.0)
            if not (0.0 <= start < end <= duration):
                raise MontageTrimInvalid(
                    f"invalid trim [{start}, {end}) for media {media_id} with duration {duration}"
                )
            cleaned[media_id] = {"start": start, "end": end}
        limits = self.get_montage_limits()
        combined = self._combined_duration(manifest.get("order", []), cleaned)
        if combined > limits.max_duration_seconds:
            excess = combined - limits.max_duration_seconds
            raise MontageDurationExceeded(
                f"combined duration {combined:.1f}s exceeds {limits.max_duration_seconds:.1f}s "
                f"limit; trim or remove {excess:.1f}s"
            )
        manifest["trims"] = cleaned
        manifest["render_revision"] = None
        self._write_manifest(package, manifest)
        self._audit.append(
            AuditEvent(
                action="montage.trim_changed",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"trims": cleaned, "package": package.folder_name},
            )
        )
        return self.get_montage_status()

    def create_review(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def approve(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def skip(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def reschedule(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def render_preview(self) -> dict:
        """Render on explicit preview (or when stale) and return the render digest."""
        package = self._require_active_package()
        self._assert_logo_configured()
        status = self.get_montage_status()
        if status.over_limit:
            raise MontageDurationExceeded(
                f"combined duration {status.combined_duration:.1f}s exceeds "
                f"{status.max_duration_seconds:.1f}s limit; {status.required_action}"
            )
        manifest = self._load_manifest(package)
        digest = self._render_digest(package, manifest)
        stale = manifest.get("render_revision") != digest
        if stale:
            self._enqueue_render(package, digest)
        return {"stale": stale, "render_revision": digest}

    def render_if_stale(self) -> bool:
        """Trigger a render only when inputs changed; no-op when fresh."""
        return bool(self.render_preview()["stale"])

    def _finalized_in_order(self, manifest: dict) -> list[tuple[str, dict]]:
        """Finalized manifest entries in explicit order, as (media_id, entry)."""
        order = manifest.get("order", [])
        by_id = {e.get("media_id"): e for e in manifest.get("media", [])}
        result = []
        for media_id in order:
            entry = by_id.get(media_id)
            if entry is None or entry.get("status") != "finalized":
                continue
            result.append((media_id, entry))
        return result

    def _render_digest(self, package: Package, manifest: dict) -> str:
        """SHA-256 over every immutable render input; preview and publish share it."""
        limits = self.get_montage_limits()
        clips = []
        for media_id, entry in self._finalized_in_order(manifest):
            clips.append(
                {
                    "media_id": media_id,
                    "filename": entry.get("filename"),
                    "content_type": entry.get("content_type"),
                    "duration": entry.get("processed", {}).get("duration"),
                    "is_video": str(entry.get("content_type", "")).startswith("video/"),
                }
            )
        inputs = {
            "order": clips,
            "trims": manifest.get("trims", {}),
            "branding": manifest.get("branding", {}),
            "caption": manifest.get("caption"),
            "photo_duration": limits.photo_duration_seconds,
        }
        canonical = json.dumps(inputs, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _enqueue_render(self, package: Package, digest: str) -> None:
        if self._render_failed_digest(package) == digest:
            return
        now = self._clock.now()
        self._jobs.create(
            Job(
                id=0,
                job_id=uuid.uuid4().hex,
                upload_id=None,
                kind="render",
                status="queued",
                payload={"package": package.folder_name, "digest": digest},
                created_at=now,
            )
        )
        self._audit.append(
            AuditEvent(
                action="render.queued",
                actor="system",
                occurred_at=now,
                details={"package": package.folder_name, "digest": digest},
            )
        )

    def _render_job(self, job: Job, package_folder: str) -> None:
        package: Package | None = None
        for candidate in [self._packages.get_active(), *self._packages.list_completed()]:
            if candidate is not None and candidate.folder_name == package_folder:
                package = candidate
                break
        if package is None:
            raise RenderFailed(f"package {package_folder} not found")
        manifest = self._load_manifest(package)
        digest = self._render_digest(package, manifest)
        build = self._build_reel(package, manifest)
        renderer = self._renderer
        if renderer is None:
            from dojo.adapters.render import FfmpegReelRenderer

            renderer = FfmpegReelRenderer()
        out = self.media_root / package.folder_name / "render" / "reel.mp4"
        work = self.media_root / "tmp" / f"render-{job.job_id}"
        renderer.render(build, work, out)
        manifest["render_revision"] = digest
        self._write_manifest(package, manifest)
        self._create_review_if_due(package, digest)
        now = self._clock.now()
        self._audit.append(
            AuditEvent(
                action="render.completed",
                actor="worker",
                occurred_at=now,
                details={
                    "package": package.folder_name,
                    "digest": digest,
                    "path": "render/reel.mp4",
                },
            )
        )

    def _build_reel(self, package: Package, manifest: dict) -> ReelBuild:
        limits = self.get_montage_limits()
        trims = manifest.get("trims", {})
        clips: list[ReelClip] = []
        for media_id, entry in self._finalized_in_order(manifest):
            processed = entry.get("processed", {})
            path = self.media_root / package.folder_name / str(processed.get("path", ""))
            is_video = str(entry.get("content_type", "")).startswith("video/")
            trim = trims.get(media_id)
            clips.append(
                ReelClip(
                    media_id=media_id,
                    path=path,
                    is_video=is_video,
                    duration=(
                        float(processed.get("duration") or 0.0)
                        if is_video
                        else limits.photo_duration_seconds
                    ),
                    trim_start=float(trim["start"]) if trim else 0.0,
                    trim_end=float(trim["end"]) if trim else None,
                )
            )
        branding = dict(manifest.get("branding", {}))
        logo = branding.get("logo_asset") or self.get_branding_defaults().logo_asset
        logo_path = self._resolve_asset(logo)
        if logo_path is None:
            raise RenderFailed("dojo logo watermark asset is required")
        return ReelBuild(
            clips=clips,
            photo_duration=limits.photo_duration_seconds,
            logo_asset=logo_path,
            intro_asset=self._resolve_asset(branding.get("intro_asset")),
            intro_duration=branding.get("intro_duration"),
            outro_asset=self._resolve_asset(branding.get("outro_asset")),
            outro_duration=branding.get("outro_duration"),
        )

    def _resolve_asset(self, value: str | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        return self.media_root / path

    def publish(self, *args: object, **kwargs: object) -> None:
        self._assert_logo_configured()
        raise NotImplementedError
