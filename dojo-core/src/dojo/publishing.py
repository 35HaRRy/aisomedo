from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from functools import wraps
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from dojo.setup import DojoSetup

from dojo.adapters.clock import ISTANBUL, SystemClock
from dojo.adapters.preview_process import PreviewCancelled
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.dashboard import NextSlot, PendingAction, PublishingDashboard, next_slot
from dojo.exceptions import (
    ActivePackageExists,
    BrandingInvalid,
    JobNotFound,
    LegacyTrimConflict,
    LogoNotConfigured,
    ManualPublishConflict,
    MediaNotFound,
    MediaNotRemovable,
    MediaNotRestorable,
    MediaValidationError,
    MetaNotConnected,
    MetaPublishFailed,
    MetaPublishUncertain,
    MetaTokenEncryptionError,
    MontageDurationExceeded,
    MontageOrderInvalid,
    MontageTrimInvalid,
    NoActivePackage,
    OccurrenceChanged,
    OccurrenceNotFound,
    PackageChanged,
    PackageCompleted,
    PackageEditConflict,
    PackageLimitExceeded,
    PlanInvalid,
    PublicationInProgress,
    PublicationNotReady,
    PushTokenInvalid,
    ReminderPolicyInvalid,
    RenderFailed,
    RescheduleTimeInvalid,
    ReviewAlreadyHandled,
    ReviewNotFound,
    ReviewStale,
    SkipRequiresConfirmation,
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
    EMPTY_PACKAGE_BODY,
    EMPTY_PACKAGE_TITLE,
    KEEP_BOTH,
    KEEP_SELECTED,
    KEEP_TARGET,
    PACKAGE_FOLDER_FORMAT,
    REVIEW_REQUIRED_BODY,
    REVIEW_REQUIRED_TITLE,
    AuditEvent,
    BrandingConfig,
    Job,
    Manifest,
    MediaEntry,
    MontageClip,
    MontageLimits,
    MontageStatus,
    Notification,
    Package,
    PackageArtifact,
    ProcessedMedia,
    ReelBuild,
    ReelClip,
    ReminderPolicy,
    SchedulePlan,
    SkipResult,
    Upload,
    UploadLimits,
    UploadStatus,
    VideoRange,
    VideoSelections,
    YayinIncelemesi,
    YayinZamani,
)
from dojo.montage import effective_duration, manifest_selections, source_duration, validate_ranges
from dojo.package_media import describe_artifacts, extension_for, public_media, resolve_artifact
from dojo.package_state import GroupEdit, content_fields, export_document, merge_edit_groups
from dojo.ports import (
    AuditStore,
    Clock,
    JobStore,
    MediaProcessor,
    MetaPublisher,
    Notifier,
    PackageStore,
    PairingStore,
    PushRegistrationStore,
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

def _package_operation[**P, T](method: Callable[P, T]) -> Callable[P, T]:
    """Serialize file/record lifecycle writes across API and worker processes."""
    @wraps(method)
    def locked(*args: P.args, **kwargs: P.kwargs) -> T:
        seam = cast("DojoPublishing", args[0])
        with seam._packages.package_lock():
            return method(*args, **kwargs)
    return locked


def _package_edit[**P, T](method: Callable[P, T]) -> Callable[P, T]:
    """Short state commands only; never wrap rendering or external publication."""
    @wraps(method)
    def edit(*args: P.args, **kwargs: P.kwargs) -> T:
        seam = cast("DojoPublishing", args[0])
        with seam._packages.package_lock(), seam._packages.command_transaction():
            return method(*args, **kwargs)
    return edit


def _review_decision[**P, T](method: Callable[P, T]) -> Callable[P, T]:
    """Reject concurrent decisions rather than queue them behind publication."""
    @wraps(method)
    def decide(*args: P.args, **kwargs: P.kwargs) -> T:
        seam = cast("DojoPublishing", args[0])
        with seam._packages.package_lock(wait=False) as acquired:
            if not acquired:
                raise PublicationInProgress(
                    "review publication or package operation is in progress"
                )
            return method(*args, **kwargs)
    return decide

REMINDER_INTERVAL_KEY = "reminders.interval_minutes"
REMINDER_START_KEY = "reminders.delivery_start"
REMINDER_END_KEY = "reminders.delivery_end"
REMINDER_TZ_KEY = "reminders.timezone"
EMPTY_REMINDERS_KEY = "reminders.empty_occurrences"


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
    return extension_for(content_type)


def _normalize(filename: str) -> str:
    """Portable case-insensitive key for a display filename (Unicode-safe)."""
    return filename.casefold()


def _read_json(path: Path) -> dict:
    """Parse a manifest, tolerating a UTF-8 BOM.

    Manifests are hand-authored during recovery and by external tools
    (Windows PowerShell 5.1 ``Set-Content -Encoding utf8`` writes a BOM).
    Plain ``utf-8`` decoding raises JSONDecodeError on that BOM, which would
    take down the whole worker tick. ``utf-8-sig`` strips a BOM when present
    and is byte-identical when absent.
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
        pairing: PairingStore | None = None,
        push_regs: PushRegistrationStore | None = None,
        setup: DojoSetup | None = None,
    ) -> None:
        self._packages = packages
        self._setup = setup
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
        self._pairing: PairingStore = (
            pairing if pairing is not None else cast(PairingStore, packages)
        )
        self._push_regs: PushRegistrationStore = (
            push_regs if push_regs is not None else cast(PushRegistrationStore, packages)
        )
        self._media = media
        self._renderer = renderer

    @_package_edit
    def ensure_active_package(self, *, requester: str | None = None) -> Package:
        """Create an active Dojo Paylaşım Paketi; raise if one already exists."""
        existing = self._packages.get_active()
        if existing is not None:
            raise ActivePackageExists(f"active package {existing.folder_name} already exists")
        return self._create_active_package(requester=requester)

    @_package_edit
    def get_or_create_active_package(self, *, requester: str | None = None) -> Package:
        """Return the active package, creating it when none exists."""
        existing = self._packages.get_active()
        if existing is not None:
            return existing
        return self._create_active_package(requester=requester)

    def _create_active_package(self, *, requester: str | None = None) -> Package:
        if self._get_publishing_package() is not None:
            raise PublicationInProgress("publication must be reconciled first")
        now = self._clock.now().astimezone(ISTANBUL)
        folder_time = now
        used_names = {p.folder_name.removesuffix("-completed")
                      for p in self._packages.list_completed()}
        folder_name = folder_time.strftime(PACKAGE_FOLDER_FORMAT)
        while folder_name in used_names:
            folder_time += timedelta(minutes=1)
            folder_name = folder_time.strftime(PACKAGE_FOLDER_FORMAT)
        folder = self.media_root / folder_name
        folder.mkdir(parents=True, exist_ok=False)
        package = self._packages.create(
            Package(id=0, folder_name=folder_name, created_at=now, status="active")
        )
        self._write_manifest(package, Manifest().to_dict())
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

    @_package_edit
    def complete_active_package(self, *, requester: str | None = None) -> Package:
        """Complete the active package and create the next empty active package."""
        existing = self._packages.get_active()
        if existing is None:
            raise NoActivePackage("no active package to complete")
        record = self._publication_record(existing)
        if record is None or record.get("status") != "completed":
            raise PublicationNotReady("only confirmed Instagram publications can complete")

        now = self._clock.now().astimezone(ISTANBUL)
        completed_folder_name = f"{existing.folder_name}-completed"

        self._jobs.cancel_media_jobs(existing.id, None, kinds=("section_preview", "thumbnail"),
                                     cancelled_at=now)
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

    @_package_operation
    def clear_active_package(
        self, *, expected_folder_name: str, expected_package_id: int | None = None,
    ) -> dict:
        """Delete this active package only, including staged work and owned records."""
        root = self.media_root.resolve()
        if expected_package_id is not None:
            journal = self.media_root / f".clearing-{expected_package_id}.json"
            trash = self.media_root / f".clearing-{expected_package_id}"
            if journal.is_symlink() or trash.is_symlink():
                raise ValueError("cleanup storage escapes media root")
            if journal.is_file():
                pending = _read_json(journal)
                if pending["result"]["folder_name"] != expected_folder_name:
                    raise PackageChanged("cleanup package identity changed")
                stored = self._packages.get_by_folder(expected_folder_name)
                if stored is None or stored.id != expected_package_id:
                    # DB deletion succeeded. A retry must purge only the old staged files.
                    if trash.exists():
                        shutil.rmtree(trash)
                    journal.unlink()
                    return pending["result"]
                # Process stopped before committing deletion. Restore staged directories first.
                for index, relative in enumerate(pending["sources"]):
                    source = self.media_root / relative
                    if source.is_symlink() or not source.resolve().is_relative_to(root):
                        raise ValueError("cleanup storage escapes media root")
                    target = trash / str(index)
                    if target.exists():
                        target.rename(source)
                if trash.exists():
                    trash.rmdir()
                journal.unlink()
        package = self._require_editor_package(expected_folder_name)
        if expected_package_id is not None and package.id != expected_package_id:
            raise PackageChanged("active package changed; refresh before clearing")
        uploads, jobs = self._packages.package_work(package)
        manifest = self._load_manifest(package)
        sources = [self.media_root / package.folder_name]
        sources.extend(self.media_root / "tmp" / u.upload_id for u in uploads)
        sources.extend(self.media_root / "tmp" / f"render-{j.job_id}" for j in jobs)
        sources.extend(self.media_root / "tmp" / f"section-preview-{j.job_id}" for j in jobs
                       if j.kind == "section_preview")
        sources.extend(self.media_root / "tmp" / f"thumbnail-{j.job_id}" for j in jobs
                       if j.kind == "thumbnail")
        for source in sources:
            resolved = source.resolve()
            if source.is_symlink() or not resolved.is_relative_to(root) or resolved == root:
                raise ValueError("package storage escapes media root")
        # Stage first: a database failure restores every directory intact.
        result = {"folder_name": package.folder_name, "upload_ids": [u.upload_id for u in uploads]}
        trash = self.media_root / f".clearing-{package.id}"
        journal = self.media_root / f".clearing-{package.id}.json"
        if trash.exists():
            trash.rmdir()  # Only an empty pre-journal directory can be safely reused.
        trash.mkdir()
        moved: list[tuple[Path, Path]] = []
        try:
            journal.write_text(json.dumps({"result": result, "sources": [
                str(source.relative_to(self.media_root)) for source in sources
            ]}), encoding="utf-8")
            for index, source in enumerate(sources):
                if source.exists():
                    target = trash / str(index)
                    source.rename(target)
                    moved.append((source, target))
            self._packages.delete_package_records(
                package, {e["media_id"] for e in manifest.get("media", [])},
            )
        except Exception:
            for source, target in reversed(moved):
                target.rename(source)
            trash.rmdir()
            journal.unlink(missing_ok=True)
            raise
        # Never hide filesystem errors or claim that a partial purge succeeded.
        shutil.rmtree(trash)
        journal.unlink()
        return result

    def get_dashboard_summary(self) -> PublishingDashboard:
        """Observe publishing state without creating work or package folders."""
        now = self._clock.now()
        package = self.get_active_package() or self._get_publishing_package()
        plan = self.get_plan()
        occurrences = self._schedule.list_all()
        by_id = {o.id: o for o in occurrences}
        manifest = self._load_manifest(package) if package else {}
        has_media = bool(self._finalized_in_order(manifest))
        digest = self._render_digest(package, manifest) if package and has_media else None
        actions = []
        reviews = self.list_pending_reviews()
        for review in reviews:
            occurrence = by_id.get(review.occurrence_id)
            ready = (
                package is not None and review.package_folder == package.folder_name
                and digest is not None and review.revision_digest == digest
                and manifest.get("render_revision") == digest
            )
            if not ready:
                continue
            try:
                resolve_artifact(self.media_root / review.package_folder, manifest,
                                 "render/reel.mp4")
            except MediaNotFound:
                continue
            actions.append(PendingAction(
                occurrence_id=review.occurrence_id, review_id=review.id,
                version=review.version,
                due_at=occurrence.due_at if occurrence else review.created_at,
                package_folder=review.package_folder,
                state="review_ready",
                review_status=review.status if review.status != "pending" else None,
            ))
        reviewed = {r.occurrence_id for r in reviews}
        for occurrence in occurrences:
            if (occurrence.status in ("pending", "due") and occurrence.due_at <= now
                    and occurrence.id not in reviewed):
                actions.append(PendingAction(
                    occurrence_id=occurrence.id, review_id=None, version=None,
                    due_at=occurrence.due_at,
                    package_folder=package.folder_name if package else None,
                    state="preparing" if has_media else "empty_package",
                ))
        return PublishingDashboard(
            generated_at=now, package=package, next_slot=next_slot(plan, occurrences, now),
            pending_actions=sorted(
                actions, key=lambda action: (action.due_at, action.occurrence_id),
            ),
            plan=plan,
            manual_review_allowed=(not reviews and not actions
                                   and not self._schedule.has_pending_exception()),
            next_slots=[NextSlot(o.kind, o.due_at, o.id) for o in sorted(
                occurrences, key=lambda o: (o.due_at, o.id),
            ) if o.status == "pending"],
        )

    # --- multi-open-folder recovery (issue #20) ---

    _SETTLED_SUFFIXES = ("-publishing", "-completed", "-recovered", "-resolved")

    @classmethod
    def _is_settled(cls, name: str) -> bool:
        """Settled folders (plus ` (N)` collision variants) are never open."""
        import re

        pattern = r"-(publishing|completed|recovered|resolved)( \(\d+\))?$"
        return re.search(pattern, name) is not None

    @classmethod
    def _is_recovered(cls, name: str) -> bool:
        """Awaiting-import folders, including ` (N)` collision variants."""
        import re

        return re.search(r"-recovered( \(\d+\))?$", name) is not None

    def _list_open_folders(self) -> list[Path]:
        if not self.media_root.is_dir():
            return []
        candidates: list[Path] = []
        for entry in self.media_root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in ("tmp", "branding") or entry.name.startswith(".clearing-"):
                continue
            if self._is_settled(entry.name):
                continue
            candidates.append(entry)
        return candidates

    def _name_held_by_other_row(self, folder_name: str) -> bool:
        """A DB row other than the active one already owns this folder name.

        ``folder_name`` is UNIQUE in Postgres. An unsuffixed folder that a
        settled row already owns cannot become the active package, because the
        alignment UPDATE would violate the index; it is quarantined instead.
        """
        row = self._packages.get_by_folder(folder_name)
        if row is None:
            return False
        active = self._packages.get_active()
        return active is None or row.id != active.id

    @staticmethod
    def _parse_folder_time(name: str) -> datetime | None:
        try:
            naive = datetime.strptime(name, PACKAGE_FOLDER_FORMAT)
        except ValueError:
            return None
        return naive.replace(tzinfo=ISTANBUL)

    def _ensure_db_active(self, folder_name: str, parsed: datetime | None) -> bool:
        """Align the active DB row with the winning folder; return True if changed."""
        existing = self._packages.get_active()
        if existing is not None and existing.folder_name == folder_name:
            return False
        manifest_path = self.media_root / folder_name / "manifest.json"
        if not manifest_path.is_file():
            manifest_path.write_text(
                json.dumps(Manifest().to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        now = self._clock.now().astimezone(ISTANBUL)
        if existing is None:
            created_at = parsed or now
            self._packages.create(
                Package(id=0, folder_name=folder_name, created_at=created_at, status="active")
            )
            return True
        self._packages.update(replace(existing, folder_name=folder_name, status="active"))
        return True

    def _notify_recovery(self, *, active: str, recovered: list[str]) -> None:
        try:
            regs = self._push_regs.list_active_device_tokens()
        except Exception:  # noqa: BLE001 - notifications never block repair
            return
        if not regs:
            return
        tokens = [r.token for r in regs]
        notification = Notification(
            title="Kurtarma tamamlandı",
            body=f"{active} aktif; {len(recovered)} klasör -recovered olarak ayrıldı.",
            data={"type": "package_recovery", "package_folder": active, "recovered": recovered},
        )
        try:
            result = self._notifier.send(notification, tokens)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("recovery notification failed")
            return
        for tok in getattr(result, "invalid_tokens", []):
            try:
                self._push_regs.remove_by_token(tok)
            except Exception:  # noqa: BLE001
                pass

    @_package_operation
    def repair_open_folders(self, *, requester: str | None = None) -> dict:
        """Reconcile multiple unsuffixed folders: newest wins, older → -recovered.

        A `-publishing` claim (uncertain Meta outcome) prohibits fresh
        publication until reconciled, so the DB row is left untouched while
        such a claim exists; filesystem quarantine still restores the
        zero-or-one-open invariant.

        A folder whose name a settled row already owns is never promoted to
        active (``folder_name`` is UNIQUE, so the alignment would fail); it is
        quarantined like any other loser.
        """
        candidates = self._list_open_folders()
        if not candidates:
            return {"active": None, "recovered": []}

        def sort_key(path: Path) -> tuple[int, float, str]:
            parsed = self._parse_folder_time(path.name)
            if parsed is not None:
                return (0, -parsed.timestamp(), path.name)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            return (1, -mtime, path.name)

        ordered = sorted(candidates, key=sort_key)
        # A candidate whose name a settled row already owns can never be the
        # active package, so it is quarantined even when it sorts newest.
        claimable = [p for p in ordered if not self._name_held_by_other_row(p.name)]
        active_path = claimable[0] if claimable else None
        existing = self._packages.get_active()
        if existing is not None and self._packages.read_package_state(existing.id) is not None:
            active_path = next(
                (p for p in claimable if p.name == existing.folder_name), active_path,
            )
        recovered_names: list[str] = []
        for loser in ordered:
            if loser == active_path:
                continue
            target = self._race_safe_recovered_target(loser.name)
            if target is None:
                continue  # lost a startup race; another process quarantined it
            recovered_names.append(target)
        publishing = self._get_publishing_package()
        db_changed = False
        if publishing is None and active_path is not None:
            db_changed = self._ensure_db_active(
                active_path.name, self._parse_folder_time(active_path.name)
            )
        if recovered_names or db_changed:
            now = self._clock.now()
            details: dict[str, object] = {
                "active": active_path.name if active_path is not None else None,
                "recovered": recovered_names,
            }
            if publishing is not None:
                details["deferred_active_db"] = True
                details["publishing"] = publishing.folder_name
            elif active_path is None:
                # Nothing claimable survived; the active row must not move.
                details["deferred_active_db"] = "all_names_settled"
            self._audit.append(
                AuditEvent(
                    action="package.recovery",
                    actor=requester or "system",
                    occurred_at=now,
                    details=details,
                )
            )
            if recovered_names and active_path is not None:
                self._notify_recovery(active=active_path.name, recovered=recovered_names)
        return {
            "active": active_path.name if active_path is not None else None,
            "recovered": recovered_names,
        }

    def _race_safe_recovered_target(self, folder_name: str) -> str | None:
        """Rename an older open folder; tolerate concurrent startup repairs."""
        older = self.media_root / folder_name
        target = self.media_root / f"{folder_name}-recovered"
        while True:
            try:
                older.rename(target)
            except FileNotFoundError:
                return None
            except FileExistsError:
                suffix = 2
                while (self.media_root / f"{folder_name}-recovered ({suffix})").exists():
                    suffix += 1
                target = self.media_root / f"{folder_name}-recovered ({suffix})"
                continue
            except OSError:
                if not older.exists() or target.exists():
                    return None
                raise
            return target.name

    def list_recovered_folders(self) -> list[str]:
        """Return `-recovered` folders awaiting import (resolved ones excluded)."""
        if not self.media_root.is_dir():
            return []
        return sorted(
            p.name for p in self.media_root.iterdir()
            if p.is_dir() and self._is_recovered(p.name)
        )

    def _read_recovered_entries(self, folder_name: str) -> tuple[Path, list[dict]]:
        folder = self.media_root / folder_name
        if not folder.is_dir() or not self._is_recovered(folder_name):
            raise MediaNotFound(f"recovered package {folder_name!r} not found")
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            raise MediaNotFound(f"manifest for {folder_name} missing")
        manifest = _read_json(manifest_path)
        if manifest.get("recovery", {}).get("resolved"):
            raise MediaNotFound(f"recovered package {folder_name!r} already resolved")
        entries = manifest.get("media", [])
        return folder, [e for e in entries if e.get("status", "finalized") == "finalized"]

    @staticmethod
    def _recovered_bytes(folder: Path, entry: dict) -> tuple[str, str, bytes]:
        media_id = str(entry.get("media_id", ""))
        filename = str(entry.get("filename", ""))
        content_type = str(entry.get("content_type", "image/jpeg"))
        entry_dir = folder / "media" / media_id
        candidate = entry_dir / filename if media_id and filename else None
        if candidate is not None and candidate.is_file():
            return filename, content_type, candidate.read_bytes()
        if entry_dir.is_dir():
            files = [p for p in entry_dir.iterdir() if p.is_file()]
            if files:
                return filename, content_type, files[0].read_bytes()
        flat = folder / filename
        if filename and flat.is_file():
            return filename, content_type, flat.read_bytes()
        raise MediaNotFound(f"recovered media {filename!r} missing")

    @_package_operation
    def import_recovered_media(
        self, folder_name: str, *, requester: str | None = None
    ) -> dict:
        """Feed recovered files through the active package's conflict workflow."""
        folder, entries = self._read_recovered_entries(folder_name)
        package = self._packages.get_active()
        if package is None:
            raise NoActivePackage("no active package to import into")
        uploads: list[dict] = []
        failed: list[dict] = []
        for entry in entries:
            try:
                filename, content_type, body = self._recovered_bytes(folder, entry)
            except MediaNotFound as exc:
                failed.append({"filename": str(entry.get("filename", "")), "error": str(exc)})
                continue
            status = self.start_upload(
                filename, content_type, len(body), requester=requester
            )
            if status.status == "receiving":
                digest = hashlib.sha256(body).hexdigest()
                self.append_upload_range(
                    status.upload_id, 0, len(body), digest, body
                )
                try:
                    completed = self.complete_upload(status.upload_id, requester=requester)
                except (UploadIncomplete, UploadConflict):
                    completed = self.get_upload_status(status.upload_id)
                uploads.append({
                    "filename": filename, "status": completed.status,
                    "upload_id": completed.upload_id,
                })
            else:
                uploads.append({
                    "filename": filename, "status": status.status,
                    "upload_id": status.upload_id,
                })
        self._audit.append(
            AuditEvent(
                action="package.recovered_import",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={
                    "folder": folder_name,
                    "imported": len(uploads),
                    "failed": [f["filename"] for f in failed],
                },
            )
        )
        return {
            "folder": folder_name,
            "imported": len(uploads),
            "uploads": uploads,
            "failed": failed,
        }

    @_package_operation
    def mark_recovered_resolved(
        self, folder_name: str, *, requester: str | None = None
    ) -> str:
        """Mark a `-recovered` folder handled so it is never imported twice."""
        import re

        if not self._is_recovered(folder_name):
            raise MediaNotFound(f"recovered package {folder_name!r} not found")
        folder = self.media_root / folder_name
        if not folder.is_dir():
            raise MediaNotFound(f"recovered package {folder_name!r} not found")
        manifest_path = folder / "manifest.json"
        if manifest_path.is_file():
            manifest = _read_json(manifest_path)
        else:
            manifest = {}
        manifest.setdefault("recovery", {})["resolved"] = True
        manifest["recovery"]["resolved_at"] = self._clock.now().isoformat()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        stem = re.sub(r"-recovered( \(\d+\))?$", "", folder_name)
        target = self.media_root / f"{stem}-resolved"
        suffix = 1
        while target.exists():
            suffix += 1
            target = self.media_root / f"{stem}-resolved ({suffix})"
        folder.rename(target)
        self._audit.append(
            AuditEvent(
                action="package.recovered_resolved",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"folder": folder_name, "resolved": target.name},
            )
        )
        return target.name

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
        *, expected_package_id: int | None = None,
    ) -> UploadStatus:
        observed = self._packages.get_active()
        expected = expected_package_id
        if expected is None:
            expected = observed.id if observed else 0
        with self._packages.package_lock():
            current = self._packages.get_active()
            if (current.id if current else 0) != expected:
                raise PackageChanged("active package changed; refresh before uploading")
            return self._start_upload(filename, content_type, declared_size_bytes, requester)

    def _start_upload(
        self, filename: str, content_type: str, declared_size_bytes: int,
        requester: str | None,
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

    @_package_operation
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

    @_package_operation
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

    @_package_operation
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
        manifest = self._load_manifest(package)
        return sum(int(entry.get("size_bytes", 0)) for entry in manifest.get("media", []))

    def _manifest_media(self, package: Package) -> list[dict]:
        manifest = self._load_manifest(package)
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
            package_id=upload.package_id,
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
        if job.kind in ("section_preview", "thumbnail") and job.status == "cancelled":
            return
        if job.status != "processing":
            raise UploadConflict(f"job {job_id} is {job.status}")
        if job.kind == "render":
            self._process_render_job(job)
            return
        if job.kind == "section_preview":
            self._process_section_preview_job(job)
            return
        if job.kind == "thumbnail":
            self._process_thumbnail_job(job)
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
        except Exception as exc:  # noqa: BLE001 - a crashed processor must not strand the upload
            self._fail_job(job, f"media processing failed: {exc}")
            return
        self.finalize_media(job.job_id, processed)

    @_package_edit
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

        manifest = self._load_manifest(package)
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
        self._write_manifest(package, manifest)

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

    @_package_operation
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

    def _preview_job_snapshot(self, job: Job) -> tuple[Package, dict, dict] | None:
        package = self._packages.get_active()
        current = self._jobs.get(job.job_id)
        if package is None or package.id != job.payload.get("package_id") \
                or package.folder_name != job.payload.get("package") \
                or current is None or current.status != "processing":
            return None
        manifest = self._load_manifest(package)
        mid = job.payload["media_id"]
        key = "thumbnails" if job.kind == "thumbnail" else "section_previews"
        record = manifest.get(key, {}).get(mid)
        if not record or record.get("generation") != job.job_id:
            return None
        entry = next((e for e in manifest.get("media", []) if e["media_id"] == mid), None)
        if entry is None:
            return None
        inputs = (self._thumbnail_input(entry) if job.kind == "thumbnail" else
                  self._section_preview_input(entry, manifest_selections(manifest).get(mid, [])))
        if inputs is None or inputs["input_digest"] != job.payload.get("input_digest"):
            return None
        return package, manifest, entry

    def _process_section_preview_job(self, job: Job) -> None:
        self._process_media_preview_job(job)

    def _process_thumbnail_job(self, job: Job) -> None:
        self._process_media_preview_job(job)

    def _process_media_preview_job(self, job: Job) -> None:
        thumbnail = job.kind == "thumbnail"
        key = "thumbnails" if thumbnail else "section_previews"
        mid = job.payload["media_id"]
        prefix = "thumbnail" if thumbnail else "section-preview"
        work = self.media_root / "tmp" / f"{prefix}-{job.job_id}"
        staged = work / ("thumbnail.jpg" if thumbnail else "sections.mp4")
        age = max(0.0, (self._clock.now() - (job.claimed_at or self._clock.now())).total_seconds())
        deadline = monotonic() + 900 - age

        def cancelled() -> bool:
            with self._packages.read_snapshot():
                if self._preview_job_snapshot(job) is None:
                    return True
            if monotonic() >= deadline:
                raise RenderFailed("preview worker deadline exceeded")
            return False

        try:
            with self._packages.package_lock(), self._packages.command_transaction():
                captured = self._preview_job_snapshot(job)
                if captured is None:
                    raise PreviewCancelled()
                package, manifest, _ = captured
                source = self.get_media_preview(mid, expected_folder_name=package.folder_name).path
                manifest[key][mid]["status"] = "processing"
                self._write_manifest(package, manifest)
            renderer = self._renderer
            if renderer is None:
                from dojo.adapters.render import FfmpegReelRenderer

                renderer = FfmpegReelRenderer()
            if thumbnail:
                renderer.render_thumbnail(source, staged, cancelled=cancelled)
                duration = None
            else:
                clips = [ReelClip(media_id=mid, path=source, is_video=True,
                    duration=r["end"] - r["start"], trim_start=r["start"], trim_end=r["end"])
                    for r in job.payload["ranges"]]
                renderer.render_sections(clips, work, staged, cancelled=cancelled)
                duration = renderer.probe_duration(staged, cancelled=cancelled)
            with self._packages.package_lock(), self._packages.command_transaction():
                current = self._preview_job_snapshot(job)
                if current is None:
                    raise PreviewCancelled()
                package, manifest, _ = current
                relative = f"media/{mid}/previews/{job.job_id}{'.jpg' if thumbnail else '.mp4'}"
                destination = self.media_root / package.folder_name / relative
                if not destination.resolve().is_relative_to(
                    (self.media_root / package.folder_name).resolve(),
                ):
                    raise ValueError("preview storage escapes package")
                destination.parent.mkdir(parents=True, exist_ok=True)
                staged.replace(destination)
                manifest[key][mid].update(status="ready", artifact_ref=relative, duration=duration)
                if self._jobs.finish_if_processing(job.job_id, status="done",
                                                  finished_at=self._clock.now()) is None:
                    raise PreviewCancelled()
                self._write_manifest(package, manifest)
        except PreviewCancelled:
            self._jobs.finish_if_processing(job.job_id, status="cancelled",
                                             finished_at=self._clock.now())
        except Exception as exc:
            with self._packages.package_lock(), self._packages.command_transaction():
                current = self._preview_job_snapshot(job)
                finished = self._jobs.finish_if_processing(
                    job.job_id, status="failed" if current else "cancelled",
                    finished_at=self._clock.now(),
                    error_reason=(f"preview processing failed ({type(exc).__name__})"
                                  if current else None),
                )
                if current is not None and finished is not None:
                    package, manifest, _ = current
                    manifest[key][mid].update(status="failed", artifact_ref=None, duration=None)
                    self._write_manifest(package, manifest)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _maintain_media_preview_jobs(self) -> None:
        package = self._packages.get_active()
        if package is None:
            return
        manifest = self._load_manifest(package)
        selections = manifest_selections(manifest)
        now = self._clock.now()
        for entry in manifest.get("media", []):
            mid = entry["media_id"]
            for key, kind, inputs in (
                ("thumbnails", "thumbnail", self._thumbnail_input(entry)),
                ("section_previews", "section_preview",
                 self._section_preview_input(entry, selections.get(mid, []))),
            ):
                if inputs is None:
                    continue
                records = manifest.setdefault(key, {})
                if mid not in records:
                    records[mid] = self._enqueue_media_preview(package, mid, inputs, kind=kind)
                record = records[mid]
                job = self._jobs.get(record["generation"])
                if job is not None and job.status == "processing" and job.claimed_at is not None \
                        and job.claimed_at + timedelta(seconds=905) <= now:
                    finished = self._jobs.finish_if_processing(
                        job.job_id, status="failed", finished_at=now,
                        error_reason="preview worker deadline exceeded",
                    )
                    if finished is not None:
                        record.update(status="failed", artifact_ref=None, duration=None)
        self._write_manifest(package, manifest)

    def _process_render_job(self, job: Job) -> None:
        payload = job.payload or {}
        try:
            self._render_job(job, str(payload.get("package", "")))
        except (RenderFailed, MontageDurationExceeded, MontageTrimInvalid) as exc:
            with self._packages.package_lock(), self._packages.command_transaction():
                if self._jobs.get(job.job_id) is None:
                    shutil.rmtree(self.media_root / "tmp" / f"render-{job.job_id}",
                                  ignore_errors=True)
                    return  # Cleanup deleted this job while its renderer was running.
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
        with self._packages.package_lock():
            if self._jobs.get(job.job_id) is not None:
                self._jobs.update(
                    replace(job, status="done", finished_at=self._clock.now(), error_reason=None)
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

    @_package_edit
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
        digest = self._render_digest(package, manifest)
        if payload.get("digest") == digest and manifest.get("render_revision") != digest:
            manifest.setdefault("recovery", {})["render_failed_digest"] = digest
            self._write_manifest(package, manifest)
        shutil.rmtree(self.media_root / "tmp" / f"render-{job.job_id}", ignore_errors=True)

    def evaluate_due_work(self) -> None:
        """Scheduler trigger: materialize due slots, then create durable reviews.

        Must run inside ``try_emission_leadership`` on the one shared store
        backing every port of this instance (the worker's ``run_tick`` owns
        that scope). All writes then join the lock-holding transaction, so a
        disconnected former leader cannot keep emitting and an emission
        exception rolls the whole turn back for a later-tick retry. Render
        and HTTP work stays outside: ``process_job`` is called separately,
        after the scope closes.
        """
        with self._packages.package_lock(wait=False) as acquired:
            if not acquired:
                return
            with self._packages.command_transaction():
                self._maintain_media_preview_jobs()
                if self._setup is not None and not self._setup.is_ready():
                    return
                self.ensure_schedule_upto()
                self._ensure_reviews_for_due()

    @_package_edit
    def _ensure_reviews_for_due(self) -> None:
        """Create at most one durable review per due occurrence for the active revision.

        A review is only created once a render is materialized. For a non-empty package
        we enqueue a render when stale (the render job's completion hook creates the
        review) or, when the render is already current, create it directly. An empty
        active package creates no review and leaves the occurrence pending.
        """
        self._select_due_occurrence()
        package = self._packages.get_active()
        if package is None:
            return
        manifest = self._load_manifest(package)
        if not self._finalized_in_order(manifest):
            return
        try:
            self._validate_montage(manifest)
        except (MontageDurationExceeded, MontageTrimInvalid):
            # Keep due occurrences pending until the editor makes inputs eligible.
            return
        digest = self._render_digest(package, manifest)
        if manifest.get("render_revision") == digest:
            self._create_review_if_due(package, digest)
        else:
            self._enqueue_render(package, digest)

    @_package_edit
    def _create_review_if_due(self, package: Package, digest: str) -> None:
        """Create one durable review for the latest due occurrence and revision.

        Idempotent: a review already recorded for ``(occurrence_id, revision_digest)``
        is never duplicated, so scheduler re-runs and restarts add nothing.
        """
        if self._setup is not None and not self._setup.is_ready():
            return
        occurrence = self._select_due_occurrence()
        if occurrence is None:
            return
        existing = self._reviews.get_by_occurrence_revision(occurrence.id, digest)
        if existing is not None and (
            existing.status != "skipped" or existing.resolved_by != "worker"
        ):
            return
        self._skip_superseded_reviews(occurrence.id, digest=digest)
        if existing is not None:
            # Only revision supersession leaves the same occurrence due. User decisions
            # resolve it, so they can never reach this path or be reopened by a render.
            reopened = self._reviews.update(replace(
                existing, status="pending", version=existing.version + 1,
                resolved_at=None, resolved_by=None, last_reminded_at=None,
            ))
            self._audit.append(AuditEvent(
                action="review.reopened", actor="worker", occurred_at=self._clock.now(),
                details={"review_id": reopened.id, "occurrence_id": occurrence.id,
                         "revision_digest": digest, "version": reopened.version},
            ))
            return
        manifest = self._load_manifest(package)
        caption = manifest.get("caption")
        now = self._clock.now()
        self._reviews.create_review_once(
            YayinIncelemesi(
                id=0,
                occurrence_id=occurrence.id,
                package_folder=package.folder_name,
                revision_digest=digest,
                caption=caption,
                status="pending",
                created_at=now,
            ),
            audit=AuditEvent(
                action="review.created",
                actor="worker",
                occurred_at=now,
                details={
                    "occurrence_id": occurrence.id,
                    "package": package.folder_name,
                    "revision_digest": digest,
                },
            ),
        )

    def _select_due_occurrence(self) -> YayinZamani | None:
        """Only the latest due occurrence owns the pending review, including render waits."""
        if any(r.status == "publishing" for r in self._reviews.list_pending()):
            return None  # Never supersede an Instagram request still being reconciled.
        plan = self.get_plan()
        due = [o for o in self._schedule.list_due(self._clock.now())
               if o.kind != "regular" or plan.enabled]
        occurrence = max(due, key=lambda o: (o.due_at, o.id), default=None)
        if occurrence is None:
            return None
        self._skip_superseded_reviews(occurrence.id)
        for older in due:
            if older.id != occurrence.id:
                self._resolve_occurrence(older.id, self._clock.now())
        if occurrence.status == "pending":
            occurrence = self._schedule.update(replace(occurrence, status="due"))
        return occurrence

    def _skip_superseded_reviews(self, occurrence_id: int, *, digest: str | None = None) -> None:
        now = self._clock.now()
        for review in self._reviews.list_pending():
            if (review.occurrence_id == occurrence_id
                    and (digest is None or review.revision_digest == digest)):
                continue
            skipped = self._reviews.resolve_if_pending(
                review.id, review.version, "skipped", now, "worker",
            )
            if skipped is None:
                continue
            if review.occurrence_id != occurrence_id:
                self._resolve_occurrence(review.occurrence_id, now)
            self._audit.append(AuditEvent(
                action="review.skipped", actor="worker", occurred_at=now,
                details={"review_id": review.id, "occurrence_id": review.occurrence_id,
                         "status": "skipped", "superseded_by_occurrence_id": occurrence_id},
            ))

    def list_pending_reviews(self) -> list[YayinIncelemesi]:
        return self._reviews.list_pending()

    def get_review_detail(self, review_id: int) -> dict:
        """Observe one review; never substitute another package or render revision."""
        review = self._reviews.get(review_id)
        if review is None:
            raise ReviewNotFound(f"review {review_id} not found")
        ready = False
        if review.status in ("pending", "failed", "uncertain"):
            try:
                self.get_render_preview(expected_folder_name=review.package_folder,
                                        expected_revision=review.revision_digest)
                ready = True
            except (NoActivePackage, PackageChanged, MediaNotFound):
                pass
        regular = self._schedule.next_regular_after(self._clock.now())
        return {"review": asdict(review), "render_ready": ready,
                "next_regular_at": regular.due_at if regular else None}

    def list_audit(self, limit: int = 50) -> list[AuditEvent]:
        return self._audit.list_recent(limit=limit)

    # --- reminder policy & push registrations ---

    def get_reminder_policy(self) -> ReminderPolicy:
        interval = self._settings.get(REMINDER_INTERVAL_KEY)
        start_raw = self._settings.get(REMINDER_START_KEY)
        end_raw = self._settings.get(REMINDER_END_KEY)
        tz = self._settings.get(REMINDER_TZ_KEY)
        default = ReminderPolicy()
        interval_minutes = (
            int(cast(int, interval)) if interval is not None else default.interval_minutes
        )
        delivery_start = (
            time.fromisoformat(str(start_raw))
            if isinstance(start_raw, str) and start_raw else default.delivery_start
        )
        delivery_end = (
            time.fromisoformat(str(end_raw))
            if isinstance(end_raw, str) and end_raw else default.delivery_end
        )
        timezone = str(tz) if isinstance(tz, str) and tz else default.timezone
        return ReminderPolicy(
            interval_minutes=interval_minutes,
            delivery_start=delivery_start,
            delivery_end=delivery_end,
            timezone=timezone,
        )

    def set_reminder_policy(
        self, policy: ReminderPolicy, requester: str | None = None
    ) -> ReminderPolicy:
        if policy.interval_minutes <= 0:
            raise ReminderPolicyInvalid("interval must be positive")
        if policy.delivery_start == policy.delivery_end:
            raise ReminderPolicyInvalid("delivery window start and end must differ")
        if policy.timezone != "Europe/Istanbul":
            raise ReminderPolicyInvalid("only Europe/Istanbul timezone is supported")
        now = self._clock.now()
        self._settings.set(REMINDER_INTERVAL_KEY, policy.interval_minutes, updated_at=now)
        self._settings.set(REMINDER_START_KEY, policy.delivery_start.isoformat(), updated_at=now)
        self._settings.set(REMINDER_END_KEY, policy.delivery_end.isoformat(), updated_at=now)
        self._settings.set(REMINDER_TZ_KEY, policy.timezone, updated_at=now)
        self._audit.append(
            AuditEvent(
                action="reminders.policy_updated",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "interval_minutes": policy.interval_minutes,
                    "delivery_start": policy.delivery_start.isoformat(),
                    "delivery_end": policy.delivery_end.isoformat(),
                    "timezone": policy.timezone,
                },
            )
        )
        return policy

    def register_push_token(self, client_id: int, token: str) -> None:
        cleaned = token.strip()
        if not cleaned:
            raise PushTokenInvalid("push token is required")
        client = self._pairing.find_client_by_id(client_id)
        if client is None:
            raise PushTokenInvalid("unknown client")
        if client.kind != "device":
            raise PushTokenInvalid("only device clients can register push tokens")
        if client.revoked_at is not None:
            raise PushTokenInvalid("revoked client cannot register push token")
        now = self._clock.now()
        self._push_regs.register_token(client_id, cleaned, now)
        self._audit.append(
            AuditEvent(
                action="push.token_registered",
                actor=str(client_id),
                occurred_at=now,
                details={"client_id": client_id},
            )
        )

    def remove_push_token(self, client_id: int) -> None:
        now = self._clock.now()
        self._push_regs.remove_by_client(client_id)
        self._audit.append(
            AuditEvent(
                action="push.token_removed",
                actor=str(client_id),
                occurred_at=now,
                details={"client_id": client_id},
            )
        )

    @staticmethod
    def _in_delivery_window(now_t: time, start: time, end: time) -> bool:
        if start < end:
            return start <= now_t < end
        # crosses midnight
        return now_t >= start or now_t < end

    @_package_operation
    def send_due_reminders(self) -> None:
        logger = logging.getLogger(__name__)
        policy = self.get_reminder_policy()
        now = self._clock.now()
        package = self._packages.get_active()
        folder = package.folder_name if package else None
        empty = (self._schedule.list_due(now) if package is not None
                 and not self._finalized_in_order(self._load_manifest(package))
                 and self._get_publishing_package() is None else [])
        empty = [o for o in empty if not self._reviews.has_for_occurrence(o.id)]
        raw_cadence = self._settings.get(EMPTY_REMINDERS_KEY)
        cadence: dict[str, dict[str, str]] = {}
        for occurrence in empty:
            entry = raw_cadence.get(str(occurrence.id)) if isinstance(raw_cadence, dict) else None
            if not isinstance(entry, dict) or entry.get("package_folder") != folder:
                continue
            try:
                at = datetime.fromisoformat(entry["last_reminded_at"])
                if at.tzinfo is not None and at <= now:
                    cadence[str(occurrence.id)] = {
                        "package_folder": str(folder), "last_reminded_at": at.isoformat(),
                    }
            except (KeyError, TypeError, ValueError):
                continue
        # Prune stale/corrupt identities even outside quiet hours or without devices.
        if raw_cadence is not None and raw_cadence != cadence:
            self._settings.set(EMPTY_REMINDERS_KEY, cadence, updated_at=now)
        now_local = now.astimezone(ISTANBUL)
        if not self._in_delivery_window(
            now_local.time(), policy.delivery_start, policy.delivery_end
        ):
            return
        pending = self._reviews.list_pending()
        # select eligible by interval
        eligible: list[YayinIncelemesi] = []
        interval = timedelta(minutes=policy.interval_minutes)
        for review in pending:
            if review.status == "publishing":
                continue
            if review.last_reminded_at is None:
                eligible.append(review)
            elif now - review.last_reminded_at >= interval:
                eligible.append(review)
        regs = self._push_regs.list_active_device_tokens()
        if not regs:
            return
        tokens = [r.token for r in regs]
        notifications: list[tuple[Notification, YayinIncelemesi | None]] = []
        for review in eligible:
            notifications.append((Notification(
                title=REVIEW_REQUIRED_TITLE,
                body=REVIEW_REQUIRED_BODY,
                data={
                    "type": "review_required",
                    "review_id": str(review.id),
                    "review_version": str(review.version),
                    "package_folder": review.package_folder,
                },
            ), review))
        for occurrence in empty:
            entry = cadence.get(str(occurrence.id))
            if entry and now - datetime.fromisoformat(entry["last_reminded_at"]) < interval:
                continue
            notifications.append((Notification(
                title=EMPTY_PACKAGE_TITLE, body=EMPTY_PACKAGE_BODY,
                data={"type": "empty_package", "occurrence_id": str(occurrence.id),
                      "package_folder": str(folder)},
            ), None))
        for notification, target_review in notifications:
            if not tokens:
                break
            identity: dict[str, object] = ({"review_id": target_review.id} if target_review else {
                "occurrence_id": int(str(notification.data["occurrence_id"])),
                "package": folder,
            })
            try:
                result = self._notifier.send(notification, tokens)
            except Exception as exc:  # noqa: BLE001
                logger.exception("reminder send failed for %s", identity)
                self._audit.append(
                    AuditEvent(
                        action="notification.failed",
                        actor="worker",
                        occurred_at=now,
                        details={**identity, "error": str(exc)},
                    )
                )
                continue
            # handle invalid tokens
            for tok in getattr(result, "invalid_tokens", []):
                try:
                    self._push_regs.remove_by_token(tok)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to remove invalid token")
            tokens = [tok for tok in tokens if tok not in getattr(result, "invalid_tokens", [])]
            # audit sent
            delivered = len(getattr(result, "delivered", []))
            invalid = len(getattr(result, "invalid_tokens", []))
            transient = len(getattr(result, "transient_failures", []))
            self._audit.append(
                AuditEvent(
                    action="notification.sent",
                    actor="worker",
                    occurred_at=now,
                    details={
                        **identity,
                        "delivered": delivered,
                        "invalid": invalid,
                        "transient": transient,
                    },
                )
            )
            # persist timestamp after completed batch
            try:
                if target_review is None:
                    cadence[str(notification.data["occurrence_id"])] = {
                        "package_folder": str(folder), "last_reminded_at": now.isoformat(),
                    }
                    self._settings.set(EMPTY_REMINDERS_KEY, dict(cadence), updated_at=now)
                else:
                    self._reviews.update_last_reminded_at(target_review.id, now)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist last_reminded_at for %s", identity)

    def add_media(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def get_conflict_preview(self, upload_id: str, target_media_id: str) -> tuple[Path, str]:
        """Resolve a current conflict target's normalized media, never an arbitrary file."""
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise UploadNotFound("upload not found")
        package = self._packages.get_active()
        if upload.status != "conflict" or package is None or upload.package_id != package.id:
            raise UploadConflict("upload is no longer an active conflict")
        target = next(
            (entry for entry in self._manifest_collisions(package, upload.filename)
             if entry.get("media_id") == target_media_id),
            None,
        )
        if target is None:
            raise MediaNotFound("conflict target not found")
        processed = target.get("processed", {})
        if not isinstance(processed, dict):
            raise MediaNotFound("conflict preview unavailable")
        content_type = processed.get("content_type")
        if not isinstance(content_type, str):
            raise MediaNotFound("conflict preview unavailable")
        extension = {"image/jpeg": ".jpg", "video/mp4": ".mp4"}.get(content_type)
        reference = f"media/{target_media_id}/processed{extension}"
        if extension is None or processed.get("path") != reference:
            raise MediaNotFound("conflict preview unavailable")
        root = (self.media_root / package.folder_name).resolve()
        path = (root / reference).resolve()
        if (not root.is_relative_to(self.media_root.resolve())
                or not path.is_relative_to(root) or not path.is_file()):
            raise MediaNotFound("conflict preview unavailable")
        return path, str(content_type)

    @_package_operation
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
                # Compatible conflicts share one normalized filename, hence targets.
                # Preserve the explicitly previewed target even in a bulk decision.
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

    @_package_edit
    def remove_media(
        self, media_id: str, requester: str | None = None, *,
        expected_folder_name: str | None = None,
    ) -> None:
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
            expected_folder_name=expected_folder_name,
        )

    @_package_edit
    def restore_media(
        self, media_id: str, requester: str | None = None, *,
        expected_folder_name: str | None = None,
    ) -> None:
        """Return removed ``media_id`` to the active montage."""
        self._toggle_media(
            media_id,
            from_status="removed",
            to_status="finalized",
            action="media.restored",
            requester=requester,
            expected_folder_name=expected_folder_name,
        )

    def _toggle_media(
        self,
        media_id: str,
        *,
        from_status: str,
        to_status: str,
        action: str,
        requester: str | None,
        expected_folder_name: str | None = None,
    ) -> None:
        package = self._require_editor_package(expected_folder_name)
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
        manifest["render_revision"] = None
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

    def _require_editor_package(self, expected_folder_name: str | None) -> Package:
        package = self._require_active_package()
        if expected_folder_name is not None and package.folder_name != expected_folder_name:
            raise PackageChanged("active package changed; refresh the editor")
        return package

    @contextmanager
    def conditional_package_operation(
        self, package_id: int, content_revision: int, *, allow_missing: bool = False,
    ) -> Iterator[None]:
        """Fence legacy commands against the exact package the user displayed."""
        with self._packages.package_lock():
            package = self._packages.get_active()
            if package is None:
                if allow_missing:
                    yield
                    return
                raise NoActivePackage("no active package")
            state = self._packages.read_package_state(package.id)
            if package.id != package_id or state is None \
                    or state.content_revision != content_revision:
                raise PackageChanged("package content changed; refresh before retrying")
            yield

    def list_completed_packages(self) -> list[Package]:
        """Return completed packages (read-only historical packages)."""
        return self._packages.list_completed()

    def get_active_editor(self) -> dict:
        package = self._require_active_package()
        state = self._packages.read_package_state(package.id)
        if state is None:
            raise MediaNotFound("package state missing")
        manifest = state.document
        root = self.media_root / package.folder_name
        artifacts = describe_artifacts(root, manifest)
        selections = manifest_selections(manifest)
        limits = self.get_montage_limits()
        media = []
        for entry in manifest.get("media", []):
            mid = entry.get("media_id")
            items = [a for a in artifacts if a["kind"] != "render"
                     and a["artifact_ref"].split("/")[1] == mid]
            preview = next((a["artifact_ref"] for a in items
                            if a["kind"] == "processed" and a["available"]), None)
            is_video = str(entry.get("content_type", "")).startswith("video/")
            source = source_duration(entry) if is_video else None
            media.append({
                **public_media(entry), "is_video": is_video, "source_duration": source,
                "effective_duration": effective_duration(
                    entry, selections.get(mid), limits.photo_duration_seconds
                ) if not is_video or source is not None else None,
                "preview_ref": preview, "artifacts": items,
            })
        digest = self._render_digest(package, manifest)
        stale = manifest.get("render_revision") != digest
        render_artifact = next(a for a in artifacts if a["kind"] == "render")
        _, jobs = self._packages.package_work(package)
        render_jobs = sorted(
            (j for j in jobs if j.kind == "render" and j.payload.get("digest") == digest),
            key=lambda j: j.id, reverse=True,
        )
        render_status = "stale" if stale and render_artifact["available"] else "missing"
        if not stale and render_artifact["available"]:
            render_status = "ready"
        elif render_jobs and render_jobs[0].status in ("queued", "processing", "failed"):
            render_status = render_jobs[0].status
        return {
            "package": dict(package.__dict__),
            "content_revision": state.content_revision,
            "view_revision": state.view_revision,
            "render_stale": stale,
            "render_status": render_status,
            "render_revision": manifest.get("render_revision"),
            "media": media, "montage": self._montage_status(manifest).to_dict(),
        }

    def get_render_preview(
        self, *, expected_folder_name: str, expected_revision: str | None = None,
    ) -> PackageArtifact:
        package = self._require_editor_package(expected_folder_name)
        manifest = self._load_manifest(package)
        revision = manifest.get("render_revision")
        if (revision != self._render_digest(package, manifest)
                or expected_revision is not None and expected_revision != revision):
            raise MediaNotFound("saved montage render is not current")
        return resolve_artifact(self.media_root / package.folder_name, manifest, "render/reel.mp4")

    def get_media_preview(self, media_id: str, *, expected_folder_name: str) -> PackageArtifact:
        package = self._require_editor_package(expected_folder_name)
        manifest = self._load_manifest(package)
        root = self.media_root / package.folder_name
        entry = next((e for e in manifest.get("media", []) if e.get("media_id") == media_id), None)
        if entry is None or entry.get("status") not in ("finalized", "removed"):
            raise MediaNotFound("media preview is unavailable")
        prefix = "removed" if entry["status"] == "removed" else "media"
        suffix = extension_for(str(entry.get("processed", {}).get("content_type", "")))
        reference = f"{prefix}/{media_id}/processed{suffix}"
        return resolve_artifact(root, manifest, reference)

    def resolve_completed_artifact(self, folder_name: str, artifact_ref: str) -> PackageArtifact:
        package = self._get_completed_package(folder_name)
        return resolve_artifact(self.media_root / package.folder_name,
                                self._load_manifest(package), artifact_ref)

    def browse_completed_package(self, folder_name: str) -> dict:
        """Return a read-only manifest view of a completed package."""
        package = self._get_completed_package(folder_name)
        manifest = self._load_manifest(package)
        return {
            "folder_name": package.folder_name,
            "media": [public_media(entry) for entry in manifest.get("media", [])],
            "order": manifest.get("order", []),
            "caption": manifest.get("caption"),
            "render_revision": manifest.get("render_revision"),
            "artifacts": describe_artifacts(self.media_root / package.folder_name, manifest),
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
        state = self._packages.read_package_state(package.id)
        if state is None:
            raise MediaNotFound(f"database state for {package.folder_name} missing")
        return state.document

    def _write_manifest(self, package: Package, manifest: dict) -> None:
        with self._packages.command_transaction():
            old = self._packages.read_package_state(package.id, for_update=True)
            if old is not None and old.document == manifest:
                return
            self._reconcile_section_previews(package, old.document if old else {}, manifest)
            changed = old is None or content_fields(old.document) != content_fields(manifest)
            self._packages.write_package_state(package.id, manifest, content_changed=changed)
            self._packages.queue_change(["dashboard", "publication", f"package:{package.id}"])
            self._packages.after_commit(
                f"manifest:{package.id}", lambda: self.export_manifest(package),
            )

    @staticmethod
    def _section_preview_input(entry: dict | None, ranges: list[VideoRange]) -> dict | None:
        if not entry or entry.get("status") != "finalized" or not ranges \
                or not isinstance(entry.get("processed"), dict) \
                or not str(entry.get("content_type", "")).startswith("video/"):
            return None
        try:
            ranges = validate_ranges(ranges, source_duration(entry) or 0)
        except MontageTrimInvalid:
            return None  # Recovery may persist an ineligible source; do not enqueue invalid work.
        processed = entry.get("processed", {})
        source = {"media_id": entry["media_id"], "uploaded_at": entry.get("uploaded_at"),
                  "filename": entry.get("filename"), "processed": {
                      key: processed.get(key) for key in ("path", "size_bytes", "duration")}}
        identity = hashlib.sha256(
            json.dumps(source, sort_keys=True, default=str).encode(),
        ).hexdigest()
        inputs = {"source_identity": identity, "ranges": ranges}
        return {**inputs, "input_digest": hashlib.sha256(
            json.dumps(inputs, sort_keys=True).encode()).hexdigest()}

    @staticmethod
    def _thumbnail_input(entry: dict | None) -> dict | None:
        if not entry or not isinstance(entry.get("processed"), dict) \
                or not str(entry.get("content_type", "")).startswith("video/"):
            return None
        duration = source_duration(entry or {})
        if duration is None:
            return None
        inputs = DojoPublishing._section_preview_input(entry, [{"start": 0.0, "end": duration}])
        if inputs is None:
            return None
        return {"source_identity": inputs["source_identity"],
                "input_digest": inputs["source_identity"]}

    def _enqueue_media_preview(
        self, package: Package, media_id: str, inputs: dict, *, retry_of: str | None = None,
        kind: str = "section_preview",
    ) -> dict:
        now = self._clock.now()
        job, _ = self._jobs.create_job_once(Job(
            id=0, job_id=uuid.uuid4().hex, upload_id=None, kind=kind,
            status="queued", created_at=now, payload={
                "package_id": package.id, "package": package.folder_name,
                "media_id": media_id, **inputs,
            },
        ))
        return {"generation": job.job_id, "input_digest": inputs["input_digest"],
                "status": job.status, "artifact_ref": None, "duration": None,
                "retry_of": retry_of}

    def _reconcile_section_previews(self, package: Package, before: dict, after: dict) -> None:
        old_media = {e["media_id"]: e for e in before.get("media", [])}
        new_media = {e["media_id"]: e for e in after.get("media", [])}
        old_ranges, new_ranges = manifest_selections(before), manifest_selections(after)
        for mid in old_media.keys() | new_media.keys():
            if self._thumbnail_input(old_media.get(mid)) != self._thumbnail_input(
                new_media.get(mid),
            ):
                self._jobs.cancel_media_jobs(package.id, mid, kinds=("thumbnail",),
                                             cancelled_at=self._clock.now())
                if mid in after.get("thumbnails", {}):
                    after["thumbnails"].pop(mid)
            previous = self._section_preview_input(old_media.get(mid), old_ranges.get(mid, []))
            current = self._section_preview_input(new_media.get(mid), new_ranges.get(mid, []))
            if previous == current:
                continue
            self._jobs.cancel_media_jobs(package.id, mid, kinds=("section_preview",),
                                         cancelled_at=self._clock.now())
            records = after.setdefault("section_previews", {})
            records.pop(mid, None)
            if current is not None:
                records[mid] = self._enqueue_media_preview(package, mid, current)

    @_package_edit
    def retry_section_preview(
        self, media_id: str, *, expected_package_id: int, expected_folder_name: str,
        expected_generation: str,
    ) -> dict:
        package = self._require_editor_package(expected_folder_name)
        if package.id != expected_package_id:
            raise PackageChanged("active package identity changed")
        manifest = self._load_manifest(package)
        record = manifest.get("section_previews", {}).get(media_id)
        if not record or expected_generation not in (record["generation"], record.get("retry_of")):
            raise PackageChanged("section preview generation changed")
        entry = next((e for e in manifest.get("media", []) if e["media_id"] == media_id), None)
        inputs = self._section_preview_input(entry, manifest_selections(manifest).get(media_id, []))
        if inputs is None or inputs["input_digest"] != record["input_digest"]:
            raise PackageChanged("saved sections changed")
        job = self._jobs.get(record["generation"])
        if job is not None and job.status in ("queued", "processing"):
            return self.get_active_editor()
        if job is None or job.status != "failed":
            raise PackageChanged("section preview is not retryable")
        manifest["section_previews"][media_id] = self._enqueue_media_preview(
            package, media_id, inputs, retry_of=expected_generation,
        )
        self._write_manifest(package, manifest)
        return self.get_active_editor()

    def export_manifest(self, package: Package) -> None:
        """Project current committed state; a disk failure never rolls it back."""
        with self._packages.package_lock():
            current = self._packages.get_by_folder(package.folder_name)
            if current is None or current.id != package.id:
                return  # Cleared or renamed since this projection was scheduled.
            export_document(self.media_root / current.folder_name / "manifest.json",
                            self._load_manifest(current))

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

    @_package_edit
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
        self._ensure_next_regular(now)
        return self.get_plan()

    @_package_edit
    def manual_publish(self, requester: str | None = None) -> YayinZamani:
        if self._reviews.list_pending() or self._schedule.has_pending_exception():
            raise ManualPublishConflict("a review or manual/oneoff publish slot is already pending")
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

    def _ensure_next_regular(self, now: datetime) -> None:
        plan = self.get_plan()
        for occurrence in self._schedule.list_all():
            if (occurrence.kind == "regular" and occurrence.status == "pending"
                    and occurrence.due_at <= now):
                self._schedule.update(replace(occurrence, status="due"))
        if not plan.enabled:
            self._schedule.prune_regular_future(now)
            return
        slot = next_slot(plan, [], now)
        if slot is None:
            return
        if self._schedule.max_regular_due_at() != slot.due_at:
            self._schedule.prune_regular_future(now)
        if not self._schedule.has_regular_at(slot.due_at):
            self._schedule.create(YayinZamani(
                id=0, kind="regular", due_at=slot.due_at, status="pending", created_at=now,
            ))

    @_package_edit
    def ensure_schedule_upto(self, now: datetime | None = None) -> None:
        now = (now or self._clock.now()).astimezone(ISTANBUL)
        self._ensure_next_regular(now)
        if self._setup is not None and not self._setup.is_ready():
            return
        plan = self.get_plan()
        if not plan.enabled or plan.anchor_date is None or plan.anchor_time is None:
            return
        created_now = self._clock.now().astimezone(ISTANBUL)
        anchor_dt = datetime.combine(
            plan.anchor_date, plan.anchor_time, tzinfo=ISTANBUL
        )
        occ_dt = anchor_dt
        while occ_dt <= now:
            if not self._schedule.has_regular_at(occ_dt):
                self._schedule.create(
                    YayinZamani(
                        id=0, kind="regular", due_at=occ_dt,
                        status="due", created_at=created_now,
                    )
                )
            occ_dt += timedelta(days=14)

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

    def patch_branding_defaults(
        self, changes: dict[str, object], requester: str | None = None
    ) -> BrandingConfig:
        """Validate a partial update before writing only the changed settings."""
        current = self.get_branding_defaults().to_dict()
        if changes.keys() - current.keys():
            raise BrandingInvalid("unknown branding field")
        updates = dict(changes)
        for key, value in changes.items():
            if value is None:
                continue
            if key.endswith("_duration"):
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or value <= 0):
                    raise BrandingInvalid("card duration must be a positive finite number")
            elif not isinstance(value, str) or not value.strip():
                raise BrandingInvalid("branding text and asset references must be nonempty")
        for kind in ("intro", "outro"):
            asset_key, duration_key = f"{kind}_asset", f"{kind}_duration"
            if asset_key in updates and updates[asset_key] is None:
                updates[duration_key] = None
            combined = {**current, **updates}
            if combined[asset_key] is None and combined[duration_key] is not None:
                raise BrandingInvalid("card duration requires a card asset")
        now = self._clock.now()
        for key, value in updates.items():
            self._settings.set(f"branding.{key}", value, updated_at=now)
        result = self.get_branding_defaults()
        self._audit.append(AuditEvent(action="branding.defaults_updated",
            actor=requester or "system", occurred_at=now, details=result.to_dict()))
        return result

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

    @_package_edit
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

    @_package_edit
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

    def get_montage_status(self) -> MontageStatus:
        package = self._require_active_package()
        return self._montage_status(self._load_manifest(package))

    def _montage_status(self, manifest: dict) -> MontageStatus:
        limits = self.get_montage_limits()
        order = manifest.get("order", [])
        trims = manifest.get("trims", {})
        selections = manifest_selections(manifest)
        by_id = {e.get("media_id"): e for e in manifest.get("media", [])}
        clips: list[MontageClip] = []
        complete = True
        for media_id in order:
            entry = by_id.get(media_id)
            if entry is None or entry.get("status") != "finalized":
                continue
            is_video = str(entry.get("content_type", "")).startswith("video/")
            source = source_duration(entry) if is_video else None
            if is_video and source is None:
                complete = False
            clips.append(
                MontageClip(
                    media_id=media_id,
                    filename=str(entry.get("filename", "")),
                    content_type=str(entry.get("content_type", "")),
                    is_video=is_video,
                    source_duration=source,
                    effective_duration=effective_duration(
                        entry, selections.get(media_id), limits.photo_duration_seconds
                    ),
                )
            )
        branding = manifest.get("branding", {})
        card_duration = sum(
            float(branding.get(f"{kind}_duration") or limits.photo_duration_seconds)
            for kind in ("intro", "outro") if branding.get(f"{kind}_asset")
        )
        combined = sum(c.effective_duration for c in clips) + card_duration
        over_limit = combined > limits.max_duration_seconds
        required_action = None
        if over_limit:
            excess = combined - limits.max_duration_seconds
            required_action = f"trim or remove {excess:.1f}s"
        if not complete:
            required_action = "video source duration unavailable; reprocess or remove the video"
        return MontageStatus(
            order=order,
            trims=trims,
            clips=clips,
            combined_duration=combined,
            max_duration_seconds=limits.max_duration_seconds,
            over_limit=over_limit,
            required_action=required_action,
            selections=selections,
            card_duration=card_duration,
            duration_complete=complete,
        )

    def _validate_montage(self, manifest: dict) -> None:
        status = self._montage_status(manifest)
        if not status.duration_complete:
            raise MontageTrimInvalid("video source duration unavailable")
        if status.over_limit:
            excess = status.combined_duration - status.max_duration_seconds
            raise MontageDurationExceeded(
                f"combined duration {status.combined_duration:.1f}s exceeds "
                f"{status.max_duration_seconds:.1f}s limit; trim or remove {excess:.1f}s"
            )

    @_package_edit
    def set_order(
        self, order: list[str], requester: str | None = None, *,
        expected_folder_name: str | None = None,
    ) -> MontageStatus:
        package = self._require_editor_package(expected_folder_name)
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
        manifest["order"] = list(order)
        self._validate_montage(manifest)
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

    @_package_edit
    def set_trims(
        self, trims: dict, requester: str | None = None, *,
        expected_folder_name: str | None = None,
    ) -> MontageStatus:
        package = self._require_editor_package(expected_folder_name)
        manifest = self._load_manifest(package)
        active = {e["media_id"] for e in manifest.get("media", [])
                  if e.get("status") == "finalized"}
        if any(len(ranges) > 1 for mid, ranges in manifest_selections(manifest).items()
               if mid in active):
            raise LegacyTrimConflict("multiple sections exist; use an updated editor")
        return self._save_selections(
            package, manifest, {mid: [trim] for mid, trim in trims.items()},
            requester=requester, action="montage.trim_changed",
        )

    @_package_edit
    def set_selections(
        self, selections: VideoSelections, requester: str | None = None, *,
        expected_folder_name: str,
        photo_durations: dict[str, float] | None = None,
    ) -> MontageStatus:
        package = self._require_editor_package(expected_folder_name)
        return self._save_selections(
            package, self._load_manifest(package), selections,
            requester=requester, action="montage.selections_changed",
            photo_durations=photo_durations,
        )

    @_package_edit
    def apply_package_edits(
        self, package_id: int, expected_folder_name: str, base_content_revision: int,
        changes: list[GroupEdit], requester: str | None = None,
    ) -> dict:
        package = self._require_editor_package(expected_folder_name)
        if package.id != package_id:
            raise PackageChanged("active package identity changed")
        state = self._packages.read_package_state(package.id, for_update=True)
        if state is None:
            raise MediaNotFound("package state missing")
        if isinstance(base_content_revision, bool) or not isinstance(base_content_revision, int) \
                or not 0 < base_content_revision <= state.content_revision:
            raise MontageTrimInvalid("invalid baseline content revision")
        try:
            merged = merge_edit_groups(
                state.document, changes,
                photo_duration_seconds=self.get_montage_limits().photo_duration_seconds,
            )
        except PackageEditConflict as exc:
            exc.content_revision = state.content_revision
            raise
        self._validate_montage(merged)
        if merged != state.document:
            merged["render_revision"] = None
            self._write_manifest(package, merged)
            self._audit.append(AuditEvent(
                action="package.edited", actor=requester or "system", occurred_at=self._clock.now(),
                details={"package": package.folder_name, "groups": [e.key for e in changes]},
            ))
        return self.get_active_editor()

    def _save_selections(
        self, package: Package, manifest: dict, selections: VideoSelections, *,
        requester: str | None, action: str,
        photo_durations: dict[str, float] | None = None,
    ) -> MontageStatus:
        if any(self._media_in_completed(mid) for mid in selections):
            raise PackageCompleted("media belongs to a completed package")
        by_id = {
            e.get("media_id"): e
            for e in manifest.get("media", [])
            if e.get("status") == "finalized"
        }
        cleaned: VideoSelections = {}
        for media_id, seconds in (photo_durations or {}).items():
            entry = by_id.get(media_id)
            if entry is None:
                raise MediaNotFound(f"media {media_id} not found in active package")
            if str(entry.get("content_type", "")).startswith("video/"):
                raise MontageTrimInvalid("photo duration applies to photos only")
            if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                    or not isfinite(seconds) or seconds < 1 / 25):
                raise MontageTrimInvalid("photo duration must be finite and at least one frame")
            entry["photo_duration_seconds"] = float(seconds)
        for media_id, ranges in selections.items():
            entry = by_id.get(media_id)
            if entry is None:
                raise MediaNotFound(f"media {media_id} not found in active package")
            if not str(entry.get("content_type", "")).startswith("video/"):
                raise MontageTrimInvalid(
                    f"media {media_id} is not a video; trims apply to videos only"
                )
            duration = source_duration(entry)
            if duration is None:
                raise MontageTrimInvalid("video source duration unavailable")
            cleaned[media_id] = validate_ranges(ranges, duration)
        removed = {e["media_id"] for e in manifest.get("media", []) if e.get("status") == "removed"}
        cleaned.update({mid: ranges for mid, ranges in manifest_selections(manifest).items()
                        if mid in removed})
        manifest["selections"] = cleaned
        manifest["trims"] = {mid: ranges[0] for mid, ranges in cleaned.items() if len(ranges) == 1}
        self._validate_montage(manifest)
        manifest["render_revision"] = None
        self._write_manifest(package, manifest)
        self._audit.append(
            AuditEvent(
                action=action,
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"selections": cleaned, "trims": manifest["trims"],
                         "package": package.folder_name},
            )
        )
        return self.get_montage_status()

    def create_review(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def _require_future_oneoff(self, occurrence_id: int, expected_due_at: datetime) -> YayinZamani:
        occurrence = next((o for o in self._schedule.list_all() if o.id == occurrence_id), None)
        if occurrence is None:
            raise OccurrenceNotFound(f"occurrence {occurrence_id} not found")
        if (occurrence.kind != "oneoff" or occurrence.status != "pending"
                or occurrence.due_at <= self._clock.now() or occurrence.due_at != expected_due_at
                or self._reviews.has_for_occurrence(occurrence_id)):
            raise OccurrenceChanged("oneoff changed; refresh before deciding")
        return occurrence

    @_package_operation
    def decide_oneoff(
        self, occurrence_id: int, expected_due_at: datetime, action: str, *,
        confirmed: bool = False, requester: str | None = None,
    ) -> dict[str, object]:
        if action not in ("review", "skip"):
            raise ValueError("invalid oneoff decision")
        if action == "skip" and not confirmed:
            raise SkipRequiresConfirmation("skip requires explicit confirmation")
        with self._schedule.emission_transaction():
            occurrence = self._require_future_oneoff(occurrence_id, expected_due_at)
            now = self._clock.now()
            updated = self._schedule.update(replace(
                occurrence, due_at=now if action == "review" else occurrence.due_at,
                status="pending" if action == "review" else "skipped",
                resolved_at=None if action == "review" else now,
            ))
            package = self.get_active_package()
            result = {"occurrence_id": updated.id, "due_at": updated.due_at,
                      "status": updated.status,
                      "package_folder": package.folder_name if package else None}
            self._audit.append(AuditEvent(
                action=("occurrence.review_requested" if action == "review"
                        else "occurrence.skipped"),
                actor=requester or "system", occurred_at=now,
                details={**result, "due_at": updated.due_at.isoformat(),
                         "old_due_at": occurrence.due_at.isoformat()},
            ))
            return result

    @_package_operation
    def change_oneoff_date(
        self, occurrence_id: int, expected_due_at: datetime, new_due_at: datetime, *,
        requester: str | None = None,
    ) -> YayinZamani:
        with self._schedule.emission_transaction():
            occurrence = self._require_future_oneoff(occurrence_id, expected_due_at)
            now = self._clock.now()
            if new_due_at.tzinfo is None:
                new_due_at = new_due_at.replace(tzinfo=ISTANBUL)
            regular = self._schedule.next_regular_after(now)
            if new_due_at <= now or (regular is not None and new_due_at >= regular.due_at):
                raise RescheduleTimeInvalid(
                    "date must be future and before the next regular publish"
                )
            updated = self._schedule.update(replace(occurrence, due_at=new_due_at))
            self._audit.append(AuditEvent(
                action="occurrence.date_changed", actor=requester or "system", occurred_at=now,
                details={"occurrence_id": occurrence_id,
                         "old_due_at": occurrence.due_at.isoformat(),
                         "new_due_at": new_due_at.isoformat()},
            ))
            return updated

    def _require_empty_occurrence(
        self, occurrence_id: int, expected_folder_name: str,
    ) -> YayinZamani:
        if self._get_publishing_package() is not None:
            raise PublicationInProgress("publication must be reconciled first")
        occurrence = next((o for o in self._schedule.list_all() if o.id == occurrence_id), None)
        if occurrence is None:
            raise OccurrenceNotFound(f"occurrence {occurrence_id} not found")
        package = self._packages.get_active()
        if (occurrence.status not in ("pending", "due") or occurrence.due_at > self._clock.now()
                or package is None or package.folder_name != expected_folder_name
                or self._reviews.has_for_occurrence(occurrence_id)
                or self._finalized_in_order(self._load_manifest(package))):
            raise OccurrenceChanged("empty occurrence changed; refresh before deciding")
        return occurrence

    @_package_operation
    def skip_empty_occurrence(
        self, occurrence_id: int, expected_folder_name: str, *, confirmed: bool,
        requester: str | None = None,
    ) -> dict[str, object]:
        if not confirmed:
            raise SkipRequiresConfirmation("skip requires explicit confirmation")
        with self._schedule.emission_transaction():
            occurrence = self._require_empty_occurrence(occurrence_id, expected_folder_name)
            self._resolve_occurrence(occurrence.id, self._clock.now())
            return self._empty_decision_result(
                occurrence.id, expected_folder_name, "skipped", requester=requester,
            )

    @_package_operation
    def reschedule_empty_occurrence(
        self, occurrence_id: int, expected_folder_name: str, new_due_at: datetime, *,
        requester: str | None = None,
    ) -> dict[str, object]:
        with self._schedule.emission_transaction():
            new_due_at = self._validate_reschedule_time(new_due_at)
            occurrence = self._require_empty_occurrence(occurrence_id, expected_folder_name)
            now = self._clock.now()
            if occurrence.kind == "oneoff":
                if occurrence.status != "pending":
                    self._require_no_pending_exception()
                oneoff = self._schedule.update(replace(
                    occurrence, due_at=new_due_at, status="pending",
                ))
            else:
                self._resolve_occurrence(occurrence.id, now)
                self._require_no_pending_exception()
                oneoff = self._schedule.create(YayinZamani(
                    id=0, kind="oneoff", due_at=new_due_at, status="pending", created_at=now,
                ))
            return self._empty_decision_result(
                occurrence.id, expected_folder_name, "rescheduled", requester=requester,
                oneoff=oneoff,
            )

    def _empty_decision_result(
        self, occurrence_id: int, folder: str, status: str, *, requester: str | None,
        oneoff: YayinZamani | None = None,
    ) -> dict[str, object]:
        now = self._clock.now()
        regular = self._schedule.next_regular_after(now)
        result: dict[str, object] = {
            "occurrence_id": occurrence_id, "package_folder": folder, "status": status,
            "next_regular_at": regular.due_at if regular else None,
            "oneoff_occurrence_id": oneoff.id if oneoff else None,
            "new_due_at": oneoff.due_at if oneoff else None,
        }
        self._audit.append(AuditEvent(
            action=f"occurrence.{status}", actor=requester or "system", occurred_at=now,
            details={**result,
                     "next_regular_at": regular.due_at.isoformat() if regular else None,
                     "new_due_at": oneoff.due_at.isoformat() if oneoff else None},
        ))
        return result

    @_review_decision
    def approve(
        self,
        review_id: int,
        version: int,
        requester: str | None = None,
    ) -> YayinIncelemesi:
        # Publication is external and can fail. Only resolve the review once
        # Instagram confirms; otherwise the user keeps every decision open.
        review = self._require_review_for_decision(
            review_id, version, to_status="approved",
        )
        self._start_publication_for_review(review, requester=requester)
        return self._reviews.get(review_id) or review

    @_review_decision
    def skip(
        self,
        review_id: int,
        version: int,
        confirmed: bool,
        requester: str | None = None,
    ) -> SkipResult:
        if not confirmed:
            raise SkipRequiresConfirmation("skip requires explicit confirmation")
        review = self._resolve_review(
            review_id,
            version,
            to_status="skipped",
            requester=requester,
        )
        now = self._clock.now()
        next_regular = self._schedule.next_regular_after(now)
        return SkipResult(
            review=review,
            next_regular_at=next_regular.due_at if next_regular is not None else None,
        )

    @_review_decision
    def reschedule(
        self,
        review_id: int,
        version: int,
        new_due_at: datetime,
        requester: str | None = None,
    ) -> YayinIncelemesi:
        with self._packages.command_transaction():
            new_due_at = self._validate_reschedule_time(new_due_at)
            review = self._resolve_review(
                review_id,
                version,
                to_status="rescheduled",
                requester=requester,
                finalize_resolution=False,
                audit=False,
            )
            return self._apply_reschedule_oneoff(review, new_due_at, requester=requester)

    def _validate_reschedule_time(self, new_due_at: datetime) -> datetime:
        now = self._clock.now().astimezone(ISTANBUL)
        if new_due_at.tzinfo is None:
            new_due_at = new_due_at.replace(tzinfo=ISTANBUL)
        if new_due_at <= now:
            raise RescheduleTimeInvalid(
                f"reschedule time {new_due_at} must be in the future"
            )
        regular = next_slot(self.get_plan(), [], now)
        if regular is not None and new_due_at >= regular.due_at:
            raise RescheduleTimeInvalid("reschedule time must be before the next regular publish")
        return new_due_at

    def _require_review_for_decision(
        self, review_id: int, version: int, *, to_status: str,
    ) -> YayinIncelemesi:
        """Load and validate one pending review without mutating it."""
        if self._get_publishing_package() is not None:
            raise PublicationInProgress("publication must be reconciled first")
        review = self._reviews.get(review_id)
        if review is None:
            raise ReviewNotFound(f"review {review_id} not found")
        if review.status == "publishing":
            raise PublicationInProgress("review publication is in progress")
        if review.status not in ("pending", "failed", "uncertain") or review.version != version:
            raise ReviewAlreadyHandled(
                f"review {review_id} was already handled by another device", review=review,
            )
        package = self._packages.get_active()
        manifest = self._load_manifest(package) if package is not None else None
        current_revision = (
            manifest.get("render_revision") if manifest is not None else None
        )
        if (
            package is None or package.folder_name != review.package_folder
            or current_revision is not None and current_revision != review.revision_digest
            or to_status == "approved" and (
                current_revision != review.revision_digest
                or self._render_digest(package, manifest or {}) != review.revision_digest
            )
        ):
            raise ReviewStale(
                f"review {review_id} is stale; content changed since it was created"
            )
        return review

    def _resolve_review(
        self,
        review_id: int,
        version: int,
        *,
        to_status: str,
        requester: str | None,
        finalize_resolution: bool = True,
        audit: bool = True,
    ) -> YayinIncelemesi:
        """Resolve one review with atomic CAS; reject stale or already-handled."""
        self._require_review_for_decision(review_id, version, to_status=to_status)
        now = self._clock.now()
        resolved = self._reviews.resolve_if_pending(
            review_id, version, to_status, now, requester
        )
        if resolved is None:
            current = self._reviews.get(review_id)
            raise ReviewAlreadyHandled(
                f"review {review_id} was already handled by another device",
                review=current,
            )
        if finalize_resolution:
            self._resolve_occurrence(resolved.occurrence_id, now)
        if audit:
            self._audit.append(
                AuditEvent(
                    action=f"review.{to_status}",
                    actor=requester or "system",
                    occurred_at=now,
                    details={
                        "review_id": resolved.id,
                        "occurrence_id": resolved.occurrence_id,
                        "package": resolved.package_folder,
                        "revision_digest": resolved.revision_digest,
                        "status": resolved.status,
                    },
                )
            )
        return resolved

    def _resolve_occurrence(self, occurrence_id: int, at: datetime) -> None:
        occurrence = next(
            (o for o in self._schedule.list_all() if o.id == occurrence_id), None
        )
        if occurrence is None or occurrence.status == "resolved":
            return
        self._schedule.update(
            replace(
                occurrence,
                status="resolved",
                resolved_at=at,
            )
        )

    def _apply_reschedule_oneoff(
        self,
        review: YayinIncelemesi,
        new_due_at: datetime,
        *,
        requester: str | None,
    ) -> YayinIncelemesi:
        """Give every reschedule a fresh occurrence/revision identity."""
        now = self._clock.now()
        self._resolve_occurrence(review.occurrence_id, now)
        self._require_no_pending_exception()
        updated = self._schedule.create(YayinZamani(
            id=0, kind="oneoff", due_at=new_due_at, status="pending", created_at=now,
        ))
        resolved_review = self._reviews.update(replace(review, oneoff_occurrence_id=updated.id))
        self._audit.append(
            AuditEvent(
                action="review.rescheduled",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "review_id": resolved_review.id,
                    "occurrence_id": updated.id,
                    "package": resolved_review.package_folder,
                    "revision_digest": resolved_review.revision_digest,
                    "status": resolved_review.status,
                    "due_at": updated.due_at.isoformat(),
                    "replaced_oneoff": updated.id != review.occurrence_id,
                },
            )
        )
        return resolved_review

    def _require_no_pending_exception(self) -> None:
        if self._schedule.has_pending_exception():
            raise ManualPublishConflict("a manual/oneoff publish slot is already pending")

    @_package_operation
    def render_preview(
        self, *, retry: bool = False, expected_folder_name: str | None = None,
    ) -> dict:
        """Render when stale; explicit retry also allows failed/completed revisions."""
        package = self._require_editor_package(expected_folder_name)
        self._assert_logo_configured()
        manifest = self._load_manifest(package)
        self._validate_montage(manifest)
        digest = self._render_digest(package, manifest)
        stale = manifest.get("render_revision") != digest
        if stale or retry:
            self._enqueue_render(package, digest, retry=retry)
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

    def _effective_branding(self, manifest: dict) -> dict:
        """Branding actually used by the renderer, including the default logo."""
        branding = dict(manifest.get("branding", {}))
        branding["logo_asset"] = (
            branding.get("logo_asset") or self.get_branding_defaults().logo_asset
        )
        return branding

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
                    **({"photo_duration": entry["photo_duration_seconds"]}
                       if "photo_duration_seconds" in entry else {}),
                }
            )
        inputs = {
            "order": clips,
            "trims": manifest.get("trims", {}),
            "branding": self._effective_branding(manifest),
            "caption": manifest.get("caption"),
            "photo_duration": limits.photo_duration_seconds,
        }
        if "selections" in manifest:
            inputs["selections"] = manifest_selections(manifest)
        canonical = json.dumps(inputs, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _enqueue_render(self, package: Package, digest: str, *, retry: bool = False) -> None:
        if not retry and self._render_failed_digest(package) == digest:
            return
        now = self._clock.now()
        self._jobs.create_job_once(
            Job(
                id=0,
                job_id=uuid.uuid4().hex,
                upload_id=None,
                kind="render",
                status="queued",
                payload={"package": package.folder_name, "digest": digest},
                created_at=now,
            ),
            audit=AuditEvent(
                action="render.queued",
                actor="system",
                occurred_at=now,
                details={"package": package.folder_name, "digest": digest},
            )
        )

    def _render_job(self, job: Job, package_folder: str) -> None:
        with self._packages.package_lock():
            package = self._packages.get_by_folder(package_folder)
            if package is None or package.status != "active":
                raise RenderFailed(f"active package {package_folder} not found")
            captured = self._packages.read_package_state(package.id)
            if captured is None:
                raise RenderFailed("package state missing")
            manifest = captured.document
            digest = self._render_digest(package, manifest)
            if job.payload.get("digest") != digest:
                raise RenderFailed("render input superseded before work began")
            if manifest.get("render_revision") == digest:
                try:
                    resolve_artifact(self.media_root / package.folder_name, manifest,
                                     "render/reel.mp4")
                    return  # A duplicate job must not replace an already reviewed artifact.
                except (MediaNotFound, ValueError):
                    pass
            build = self._build_reel(package, manifest)
        renderer = self._renderer
        if renderer is None:
            from dojo.adapters.render import FfmpegReelRenderer

            renderer = FfmpegReelRenderer()
        out = self.media_root / package.folder_name / "render" / "reel.mp4"
        work = self.media_root / "tmp" / f"render-{job.job_id}"
        staged = work / "reel.mp4"
        renderer.render(build, work, staged)
        with self._packages.package_lock(), self._packages.command_transaction():
            if self._jobs.get(job.job_id) is None:
                shutil.rmtree(work, ignore_errors=True)
                return  # Cleanup won the race; never recreate its deleted records/artifacts.
            current = self._packages.get_active()
            fresh = self._packages.read_package_state(package.id, for_update=True)
            if current is None or current.id != package.id \
                    or current.folder_name != package.folder_name or fresh is None \
                    or fresh.content_revision != captured.content_revision \
                    or self._render_digest(current, fresh.document) != digest:
                staged.unlink(missing_ok=True)
                self._audit.append(AuditEvent(
                    action="render.superseded", actor="worker", occurred_at=self._clock.now(),
                    details={"package": package.folder_name, "digest": digest},
                ))
                return
            if fresh.document.get("render_revision") == digest and out.is_file():
                staged.unlink(missing_ok=True)
                return  # Another worker already attached this immutable revision.
            out.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(out)
            manifest = fresh.document
            manifest["render_revision"] = digest
            self._write_manifest(package, manifest)
            self._create_review_if_due(package, digest)
            self._audit.append(AuditEvent(
                action="render.completed", actor="worker", occurred_at=self._clock.now(),
                details={"package": package.folder_name, "digest": digest,
                         "path": "render/reel.mp4"},
            ))

    def _build_reel(self, package: Package, manifest: dict) -> ReelBuild:
        self._validate_montage(manifest)
        limits = self.get_montage_limits()
        selections = manifest_selections(manifest)
        clips: list[ReelClip] = []
        for media_id, entry in self._finalized_in_order(manifest):
            processed = entry.get("processed", {})
            path = self.media_root / package.folder_name / str(processed.get("path", ""))
            is_video = str(entry.get("content_type", "")).startswith("video/")
            ranges = selections.get(media_id) if is_video else None
            if ranges is not None:
                for section in ranges:
                    clips.append(ReelClip(
                        media_id=media_id, path=path, is_video=True,
                        duration=section["end"] - section["start"],
                        trim_start=section["start"], trim_end=section["end"],
                    ))
            else:
                clips.append(
                    ReelClip(
                        media_id=media_id, path=path, is_video=is_video,
                        duration=effective_duration(entry, None, limits.photo_duration_seconds),
                    )
                )
        branding = self._effective_branding(manifest)
        logo_path = self._resolve_asset(branding.get("logo_asset"))
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

    def publish(self, *args: object, **kwargs: object) -> dict:
        """Legacy entry: publish the latest approved review for the active package.

        Approval already triggers publication synchronously; this path exists
        for the ``POST /api/packages/active/publish`` route as an explicit
        retry. Raises ``PublicationNotReady`` when nothing approved is ready.
        """
        self._assert_logo_configured()
        requester = kwargs.get("requester")
        if not isinstance(requester, str) and requester is not None:
            requester = None
        return self.retry_publication(requester=requester)

    # --- publication execution (issue #18) ---

    def _get_publishing_package(self) -> Package | None:
        getter = getattr(self._packages, "get_publishing", None)
        if callable(getter):
            return getter()
        return None

    def _publication_record(self, package: Package) -> dict | None:
        try:
            manifest = self._load_manifest(package)
        except MediaNotFound:
            return None
        record = manifest.get("meta", {}).get("publication")
        return dict(record) if isinstance(record, dict) else None

    def _save_publication_record(self, package: Package, record: dict) -> None:
        manifest = self._load_manifest(package)
        meta = dict(manifest.get("meta", {}))
        meta["publication"] = dict(record)
        manifest["meta"] = meta
        self._write_manifest(package, manifest)

    def _start_publication_for_review(
        self, review: YayinIncelemesi, *, requester: str | None
    ) -> None:
        if self._get_publishing_package() is not None:
            raise PublicationInProgress("another publication is already in progress")
        package = self._packages.get_active()
        if package is None or package.folder_name != review.package_folder:
            raise PublicationNotReady("approved package is no longer active")
        manifest = self._load_manifest(package)
        if manifest.get("render_revision") != review.revision_digest:
            raise ReviewStale(
                f"review {review.id} is stale; content changed since it was created"
            )
        claimed = self._claim_for_publication(package, review, requester=requester)
        self._attempt_publication(claimed, requester=requester)

    def _claim_for_publication(
        self, package: Package, review: YayinIncelemesi, *, requester: str | None
    ) -> Package:
        render_path = self.media_root / package.folder_name / "render" / "reel.mp4"
        if not render_path.is_file():
            raise RenderFailed(f"approved render for {package.folder_name} is missing")
        publishing_folder = f"{package.folder_name}-publishing"
        target = self.media_root / publishing_folder
        if target.exists():
            raise PublicationInProgress(
                f"publication folder {publishing_folder} already exists"
            )
        now = self._clock.now()
        manifest = self._load_manifest(package)
        record = {
            "status": "publishing",
            "publish_started": False,
            "revision": review.revision_digest,
            "review_id": review.id,
            "review_version": review.version,
            "caption": review.caption,
            "container_id": None,
            "media_id": None,
            "signed_url": None,
            "error": None,
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        manifest.setdefault("meta", {})["publication"] = record
        self._write_manifest(package, manifest)
        (self.media_root / package.folder_name).rename(target)
        claimed = self._packages.update(
            replace(package, status="publishing", folder_name=publishing_folder)
        )
        self._reviews.update(replace(review, status="publishing", instagram_fail_message=None))
        self._audit.append(
            AuditEvent(
                action="publication.claimed",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "package": publishing_folder,
                    "from": package.folder_name,
                    "revision": review.revision_digest,
                    "review_id": review.id,
                },
            )
        )
        return claimed

    def _attempt_publication(self, package: Package, *, requester: str | None) -> None:
        """Run one publication attempt for a ``-publishing`` package.

        Failed and uncertain outcomes restore the active package for a manual
        decision. Confirmed ingestion still in progress stays locked for polling.
        """
        record = self._publication_record(package) or {}
        if record.get("publish_started", True):
            self._mark_uncertain(package, "publish already attempted; polling required",
                                 requester=requester)
            return
        manifest = self._load_manifest(package)
        caption = record.get("caption") or manifest.get("caption") or ""
        artifact = self.media_root / package.folder_name / "render" / "reel.mp4"
        if not artifact.is_file():
            self._restore_to_active(
                package, "approved render missing", requester=requester
            )
            return
        container_id = record.get("container_id")
        signed_url = record.get("signed_url")
        if not signed_url and not container_id:
            # Fresh attempt: expose the approved render for ingestion. Resumes
            # reuse the saved container id and never mint a second container.
            try:
                signed_url = self._signed_urls.create(artifact)
            except Exception as exc:  # No request to Instagram has been made yet.
                self._restore_to_active(package, str(exc), requester=requester)
                return
            record["signed_url"] = signed_url
            record["updated_at"] = self._clock.now().isoformat()
            self._save_publication_record(package, record)
            self._audit.append(
                AuditEvent(
                    action="publication.signed_url_created",
                    actor=requester or "system",
                    occurred_at=self._clock.now(),
                    details={"package": package.folder_name, "artifact": "render/reel.mp4"},
                )
            )
        if not container_id:
            assert signed_url, "fresh attempts always mint a signed URL first"
            try:
                container_id = self._meta.create_container(str(signed_url), str(caption))
            except MetaPublishUncertain as exc:
                self._mark_uncertain(package, f"container creation uncertain: {exc}",
                                     requester=requester)
                return
            except (MetaPublishFailed, MetaNotConnected, MetaTokenEncryptionError) as exc:
                self._restore_to_active(package, str(exc), requester=requester)
                return
            except Exception as exc:
                self._mark_uncertain(package, f"container creation uncertain: {exc}",
                                     requester=requester)
                return
            record["container_id"] = container_id
            record["updated_at"] = self._clock.now().isoformat()
            self._save_publication_record(package, record)
            self._audit.append(
                AuditEvent(
                    action="publication.container_created",
                    actor=requester or "system",
                    occurred_at=self._clock.now(),
                    details={"package": package.folder_name, "container_id": container_id},
                )
            )
        try:
            status = self._meta.get_container_status(str(container_id))
        except MetaPublishUncertain as exc:
            self._mark_uncertain(package, f"container status uncertain: {exc}",
                                 requester=requester)
            return
        except Exception as exc:
            # A saved container does not prove delivery; require a manual check.
            self._mark_uncertain(package, f"container status check failed: {exc}",
                                 requester=requester)
            return
        if status in ("ERROR", "EXPIRED"):
            self._restore_to_active(
                package, f"container {container_id} reported {status}",
                requester=requester,
            )
            return
        if status != "FINISHED":
            # IN_PROGRESS or unknown: ingestion not confirmed; keep polling.
            if status == "IN_PROGRESS":
                return
            self._mark_uncertain(
                package, f"container {container_id} reported {status}",
                requester=requester,
            )
            return
        # Ingested: revoke the signed URL before the external publish call.
        try:
            if signed_url:
                self._signed_urls.revoke(str(signed_url))
        finally:
            record = self._publication_record(package) or record
            record["signed_url"] = None
            record["updated_at"] = self._clock.now().isoformat()
            self._save_publication_record(package, record)
        self._audit.append(
            AuditEvent(
                action="publication.signed_url_revoked",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"package": package.folder_name, "container_id": container_id},
            )
        )
        # Persist before sending: a crash or lost response must never resend.
        # Exclusive marker also arbitrates concurrent worker/API resumes.
        marker = self.media_root / package.folder_name / f".publish-{container_id}"
        try:
            with marker.open("x", encoding="utf-8"):
                pass
        except FileExistsError:
            return
        record["publish_started"] = True
        self._save_publication_record(package, record)
        try:
            media_id = self._meta.publish_container(str(container_id))
        except MetaPublishUncertain as exc:
            record = self._publication_record(package) or record
            record["updated_at"] = self._clock.now().isoformat()
            self._save_publication_record(package, record)
            self._mark_uncertain(package, f"publish uncertain: {exc}",
                                 requester=requester)
            return
        except Exception as exc:
            # Instagram may have published despite the lost response. The
            # uncertain review warns the user before an explicit fresh attempt.
            record = self._publication_record(package) or record
            record["updated_at"] = self._clock.now().isoformat()
            self._save_publication_record(package, record)
            self._mark_uncertain(package, f"publish failed: {exc}",
                                 requester=requester)
            return
        self._complete_publication(package, str(container_id), str(media_id),
                                   requester=requester)

    def _notify_publication_outcome(self, *, succeeded: bool,
                                           package_folder: str) -> None:
        """Best-effort push to all paired devices on success or failure."""
        try:
            regs = self._push_regs.list_active_device_tokens()
        except Exception:  # noqa: BLE001 - notifications never block publication
            return
        if not regs:
            return
        tokens = [r.token for r in regs]
        notification = Notification(
            title="Yayın Tamamlandı" if succeeded else "Yayın Başarısız",
            body=(
                f"{package_folder} Instagram'da yayınlandı."
                if succeeded
                else f"{package_folder} yayınlanamadı; yeniden deneyin."
            ),
            data={"type": "publication_confirmed" if succeeded else "publication_failed",
                  "package_folder": package_folder},
        )
        try:
            result = self._notifier.send(notification, tokens)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("publication notification failed")
            return
        for tok in getattr(result, "invalid_tokens", []):
            try:
                self._push_regs.remove_by_token(tok)
            except Exception:  # noqa: BLE001
                pass
        self._audit.append(
            AuditEvent(
                action="notification.sent",
                actor="worker",
                occurred_at=self._clock.now(),
                details={"package": package_folder,
                         "delivered": len(getattr(result, "delivered", []))},
            )
        )

    def _mark_uncertain(self, package: Package, error: str, *,
                        requester: str | None) -> None:
        self._restore_to_active(package, error, requester=requester, status="uncertain")

    def _restore_to_active(self, package: Package, error: str, *,
                            requester: str | None, status: str = "failed") -> Package:
        record = self._publication_record(package) or {}
        try:
            signed_url = record.get("signed_url")
            if signed_url:
                self._signed_urls.revoke(str(signed_url))
        except Exception:  # noqa: BLE001 - revocation is best effort
            pass
        base = package.folder_name
        active_folder = base[:-len("-publishing")] if base.endswith("-publishing") else base
        (self.media_root / base).rename(self.media_root / active_folder)
        restored = self._packages.update(
            replace(package, status="active", folder_name=active_folder)
        )
        failed = {
            "status": status,
            "revision": record.get("revision"),
            "review_id": record.get("review_id"),
            "review_version": record.get("review_version"),
            "caption": record.get("caption"),
            "container_id": record.get("container_id"),
            "media_id": None,
            "signed_url": None,
            "error": error,
            "started_at": record.get("started_at"),
            "updated_at": self._clock.now().isoformat(),
        }
        self._save_publication_record(restored, failed)
        review = self._reviews.get(int(record.get("review_id") or 0))
        if review is not None and review.status == "publishing":
            review = self._reviews.update(replace(
                review, status=status, instagram_fail_message=error,
            ))
            self._audit.append(AuditEvent(
                action=f"review.{status}", actor=requester or "system",
                occurred_at=self._clock.now(),
                details=json.loads(json.dumps(
                    asdict(review), default=lambda value: value.isoformat(),
                )),
            ))
        self._audit.append(
            AuditEvent(
                action=f"publication.{status}",
                actor=requester or "system",
                occurred_at=self._clock.now(),
                details={"package": active_folder, "error": error},
            )
        )
        self._notify_publication_outcome(succeeded=False, package_folder=active_folder)
        return restored

    def _resolve_publication_review(
        self, record: dict, *, requester: str | None,
    ) -> None:
        """Close the review only after Instagram confirmed the publication."""
        review_id = record.get("review_id")
        version = record.get("review_version")
        if not isinstance(review_id, int) or not isinstance(version, int):
            return
        now = self._clock.now()
        resolved = self._reviews.resolve_if_pending(
            review_id, version, "approved", now, requester,
        )
        if resolved is None:
            return
        self._resolve_occurrence(resolved.occurrence_id, now)
        self._audit.append(
            AuditEvent(
                action="review.approved",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "review_id": resolved.id,
                    "occurrence_id": resolved.occurrence_id,
                    "package": resolved.package_folder,
                    "revision_digest": resolved.revision_digest,
                    "status": resolved.status,
                },
            )
        )

    def _complete_publication(self, package: Package, container_id: str,
                              media_id: str | None, *, requester: str | None) -> Package:
        now = self._clock.now()
        record = self._publication_record(package) or {}
        record.update({
            "status": "completed",
            "container_id": container_id,
            "media_id": media_id,
            "signed_url": None,
            "error": None,
            "updated_at": now.isoformat(),
        })
        self._save_publication_record(package, record)
        self._audit.append(
            AuditEvent(
                action="publication.confirmed",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "package": package.folder_name,
                    "container_id": container_id,
                    "media_id": media_id,
                },
            )
        )
        self._resolve_publication_review(record, requester=requester)
        base = package.folder_name
        stem = base[:-len("-publishing")] if base.endswith("-publishing") else base
        completed_folder = f"{stem}-completed"
        (self.media_root / base).rename(self.media_root / completed_folder)
        completed = self._packages.update(
            replace(package, status="completed", folder_name=completed_folder)
        )
        self._audit.append(
            AuditEvent(
                action="package.completed",
                actor=requester or "system",
                occurred_at=now,
                details={
                    "folder_name": completed_folder,
                    "container_id": container_id,
                    "media_id": media_id,
                },
            )
        )
        self._notify_publication_outcome(succeeded=True, package_folder=completed_folder)
        if self._packages.get_active() is None and self._get_publishing_package() is None:
            try:
                self._create_active_package(requester=requester)
            except FileExistsError:
                # clock fixed in tests can collide; suffix to keep invariant
                existing = self._packages.get_active()
                if existing is None:
                    raise
        return completed

    def serve_signed_artifact(self, url_or_token: str) -> Path:
        """Resolve a signed publication URL to its artifact path for serving.

        Only the approved ``render/reel.mp4`` is ever resolvable; raw media
        paths raise. Each fetch is audited.
        """
        resolver = getattr(self._signed_urls, "resolve", None)
        if not callable(resolver):
            raise MediaNotFound("signed URL delivery is not configured")
        try:
            path = Path(resolver(url_or_token))
        except ValueError as exc:
            raise MediaNotFound(str(exc)) from exc
        self._audit.append(
            AuditEvent(
                action="publication.artifact_fetched",
                actor="meta",
                occurred_at=self._clock.now(),
                details={"artifact": "render/reel.mp4"},
            )
        )
        return path

    @_package_edit
    def recover_publication(
        self, action: str, *, confirmed: bool = False,
        new_due_at: datetime | None = None, requester: str | None = None,
    ) -> dict:
        """Recover a definite failure, reusing its still-pending review when available."""
        if self._get_publishing_package() is not None:
            raise PublicationInProgress("publication must be reconciled first")
        package = self._packages.get_active()
        record = self._publication_record(package) if package else None
        if package is None or record is None or record.get("status") not in ("failed", "uncertain"):
            raise PublicationNotReady("no failed publication to recover")
        if action not in ("review", "skip", "reschedule"):
            raise PublicationNotReady("unsupported recovery action")
        if action == "skip" and not confirmed:
            raise SkipRequiresConfirmation("skip requires explicit confirmation")
        now = self._clock.now()
        if action == "reschedule":
            if new_due_at is None:
                raise RescheduleTimeInvalid("reschedule time must be in the future")
            new_due_at = self._validate_reschedule_time(new_due_at)
        review = self._reviews.get(int(record.get("review_id") or 0))
        if review is not None and review.status in ("pending", "failed", "uncertain"):
            if action == "skip":
                self.skip(review.id, review.version, confirmed=confirmed, requester=requester)
            elif action == "reschedule":
                assert new_due_at is not None
                self.reschedule(review.id, review.version, new_due_at, requester=requester)
        elif action in ("review", "reschedule"):
            self._require_no_pending_exception()
            due_at = new_due_at if action == "reschedule" and new_due_at else now
            occurrence = self._schedule.create(
                YayinZamani(
                    id=0, kind="oneoff", due_at=due_at,
                    status="pending", created_at=now,
                )
            )
            record["recovery_occurrence_id"] = occurrence.id
        recovered = {"review": "reviewing", "skip": "skipped", "reschedule": "rescheduled"}
        record["status"] = recovered[action]
        record["updated_at"] = now.isoformat()
        self._save_publication_record(package, record)
        self._audit.append(AuditEvent(
            action=f"publication.{record['status']}", actor=requester or "system",
            occurred_at=now, details={"package": package.folder_name},
        ))
        if action == "review":
            self._ensure_reviews_for_due()
        return {"package": package.folder_name, **record, "allowed_actions": []}

    @staticmethod
    def _recovery_actions(status: object) -> list[str]:
        """Failed/uncertain reviews allow manual decisions; publishing only polls."""
        if status in ("failed", "uncertain"):
            return ["retry", "review", "skip", "reschedule"]
        if status == "publishing":
            return ["reconcile"]
        return []

    def get_publication_status(self) -> dict | None:
        package = self._get_publishing_package()
        if package is not None:
            record = self._publication_record(package) or {}
            return {
                "package": package.folder_name,
                **record,
                "allowed_actions": self._recovery_actions(record.get("status")),
            }
        active = self._packages.get_active()
        if active is not None:
            active_record = self._publication_record(active)
            if active_record is not None:
                return {
                    "package": active.folder_name,
                    **active_record,
                    "allowed_actions": self._recovery_actions(active_record.get("status")),
                }
        return None

    @_package_operation
    def retry_publication(self, *, requester: str | None = None) -> dict:
        if self._get_publishing_package() is not None:
            raise PublicationInProgress("another publication is already in progress")
        package = self._packages.get_active()
        if package is None:
            raise PublicationNotReady("no active package to publish")
        record = self._publication_record(package)
        if record is None or record.get("status") not in ("failed", "uncertain"):
            # approve() already publishes; explicit retry needs a failed attempt.
            raise PublicationNotReady(
                "no failed publication to retry; approve a review first"
            )
        manifest = self._load_manifest(package)
        if manifest.get("render_revision") != record.get("revision"):
            raise PublicationNotReady("package changed since the failed attempt")
        review = self._reviews.get(int(record.get("review_id") or 0))
        recorded_version = record.get("review_version")
        if (
            review is None or review.status not in ("pending", "failed", "uncertain", "approved")
            or isinstance(recorded_version, int) and review.version != recorded_version
        ):
            raise PublicationNotReady("pending review for retry is unavailable")
        claimed = self._claim_for_publication(package, review, requester=requester)
        self._attempt_publication(claimed, requester=requester)
        status = self.get_publication_status()
        if status is None:
            completed = self._packages.get_by_folder(
                f"{claimed.folder_name[:-len('-publishing')]}-completed"
            ) if hasattr(self._packages, "get_by_folder") else None
            if completed is not None:
                record = self._publication_record(completed) or {}
                return {"package": completed.folder_name, **record}
            raise PublicationNotReady("publication finished without a status record")
        return status

    @_package_operation
    def reconcile_publication(self, *, requester: str | None = None) -> dict | None:
        """Poll saved Meta identifiers for a ``-publishing`` package.

        Never issues a fresh external publish command: it only inspects the
        saved container and completes when Instagram confirms.
        """
        package = self._get_publishing_package()
        if package is None:
            return None
        record = self._publication_record(package) or {}
        container_id = record.get("container_id")
        if not container_id:
            self._mark_uncertain(package, "no container id recorded yet",
                                 requester=requester)
            return self.get_publication_status()
        try:
            status = self._meta.get_container_status(str(container_id))
        except MetaPublishUncertain as exc:
            self._mark_uncertain(package, f"container status uncertain: {exc}",
                                 requester=requester)
            return self.get_publication_status()
        except Exception as exc:
            # An unreadable result becomes a manual, uncertain review.
            self._mark_uncertain(package, f"container status check failed: {exc}",
                                 requester=requester)
            return self.get_publication_status()
        if status in ("ERROR", "EXPIRED"):
            if record.get("publish_started", True):
                self._mark_uncertain(package, f"container {container_id} reported {status}",
                                     requester=requester)
                return self.get_publication_status()
            self._restore_to_active(
                package, f"container {container_id} reported {status}",
                requester=requester,
            )
            return self.get_publication_status()
        if status == "PUBLISHED":
            self._complete_publication(package, str(container_id), record.get("media_id"),
                                       requester=requester)
            return self.get_publication_status()
        if status == "FINISHED" and record.get("publish_started") is False:
            # Resume ingestion only when no publish command was sent.
            self._attempt_publication(package, requester=requester)
            return self.get_publication_status()
        if status != "IN_PROGRESS":
            self._mark_uncertain(package, f"container {container_id} reported {status}",
                                 requester=requester)
        return self.get_publication_status()
