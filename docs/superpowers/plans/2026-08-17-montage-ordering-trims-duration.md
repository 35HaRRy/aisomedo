# Montage Ordering, Trims, and Duration Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship explicit montage ordering edits, per-video trims, and duration-limit enforcement for issue #10: `set_order`/`set_trims` on the deep `DojoPublishing` seam persist to the manifest, reject over-limit montages with an actionable message, and mark the render stale.

**Architecture:** Extend the deep `DojoPublishing` facade (`dojo/publishing.py`) — same as #7/#8/#9. No new tables, no migration: order, trims, and `render_revision` already live on the filesystem manifest. The video processor captures per-clip duration at finalize; trims are stored as metadata and applied by the renderer later (#12), not re-encoded here. New routes on the existing `packages` router.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, pytest, ruff, mypy. Domain tests via the in-memory seam with `StubMediaProcessor`; contract tests via FastAPI `TestClient`. Real-video duration probing is validated by the existing ffmpeg docker fixtures.

## Global Constraints

- Python `requires-python = ">=3.12"`.
- Domain vocabulary from `CONTEXT.md` / `docs/specs/dojo-reel-publishing-mvp.md`: active `Dojo Paylaşım Paketi`, immutable `media_id`, manifest contract. No new domain nouns.
- One primary seam: `DojoPublishing` in `dojo/publishing.py`. Tests assert externally visible domain outcomes, not SQL or private method order.
- Explicit montage order lives in `manifest.order`; new uploads append at finalize (already shipped in #7). Order edits must be a permutation of the finalized `media_id`s.
- Trims stored in `manifest.trims` as `{media_id: {"start": float, "end": float}}`; video-only; absent key = full clip.
- Duration: video effective = `processed.duration − (end − start)`; photo effective = `montage.photo_duration_seconds` (default `3.0`). Combined = Σ over `order`.
- Limit: `montage.max_duration_seconds` (default `90.0`) read via `SettingsStore`.
- Over-limit behavior (option A): `set_order`/`set_trims` **reject** any edit whose combined duration exceeds the limit, raising `MontageDurationExceeded` with an actionable message. Nothing is written on rejection. Never truncate or split.
- Render stale: a successful order/trim edit clears `render_revision`; new-upload finalize also clears it.
- Routes behind `get_current_client`; equal privilege device + browser; unauth → 401.
- Settings keys: `montage.max_duration_seconds`, `montage.photo_duration_seconds`. No migration.
- Lint: ruff (`E,F,I,UP`). dojo-core mypy with `disallow_untyped_defs`; backend mypy `strict`. Both pass before each task's commit.
- Commands run from repo root. Tests use `FakeClock` for deterministic time.
- Every Python task: run the focused test file first, then the package's full suite, before committing.

---

### Task 1: Duration capture — video processor, stub, finalize

Capture per-clip duration at finalize so the montage seam can compute combined duration and validate trims. Also clear `render_revision` when a new upload changes the montage.

**Files:**
- Modify: `dojo-core/src/dojo/adapters/media.py` (`_process_video`, add `_probe_duration`)
- Modify: `dojo-core/src/dojo/adapters/stubs.py` (`StubMediaProcessor`)
- Modify: `dojo-core/src/dojo/publishing.py` (`finalize_media`)
- Modify: `dojo-core/tests/test_media_processor.py` (assert duration on video output)
- Create: `dojo-core/tests/test_montage.py` (first tests: stub duration stored + render_revision cleared)

**Interfaces:**
- Consumes: `ProcessedMedia` (already has `duration: float | None = None`); `finalize_media` current media-entry construction.
- Produces:
  - `PillowFFmpegProcessor._process_video` returns `ProcessedMedia` with `duration` set (seconds, `float`).
  - `StubMediaProcessor.__init__(..., duration: float | None = None)`; `process` sets `ProcessedMedia.duration` when provided.
  - `finalize_media` stores `processed.duration` on the media entry (`processed.duration`) when not `None`, and clears `manifest.render_revision`.

- [ ] **Step 1: Write the failing tests**

Create `dojo-core/tests/test_montage.py`:
```python
from __future__ import annotations

import hashlib
import json

import pytest
from dojo import (
    DojoPublishing,
    InMemoryStore,
    NoActivePackage,
    PackageCompleted,
)
from dojo.adapters.stubs import (
    StubMediaProcessor,
    StubMetaPublisher,
    StubNotifier,
    StubSignedUrlStore,
)
from dojo.testing import FakeClock


def make_seam(tmp_path, **overrides):
    store = InMemoryStore()
    return (
        store,
        DojoPublishing(
            packages=store,
            audit=store,
            uploads=store,
            jobs=store,
            settings=store,
            media_root=tmp_path,
            clock=FakeClock(),
            meta=StubMetaPublisher(),
            notifier=StubNotifier(),
            signed_urls=StubSignedUrlStore(),
            **overrides,
        ),
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finalize_media(
    tmp_path, seam, store, *, filename="pic.jpg",
    content_type="image/jpeg", duration=None,
) -> str:
    """Upload + process one media and return its media_id."""
    seam._media = StubMediaProcessor(content_type=content_type, duration=duration)
    seam.get_or_create_active_package()
    status = seam.start_upload(filename, content_type, 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    job = seam.claim_next_job()
    assert job is not None
    seam.process_job(job.job_id)
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    return next(e["media_id"] for e in manifest["media"] if e["filename"] == filename)


def test_video_entry_stores_duration(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=12.0,
    )
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    entry = next(e for e in manifest["media"] if e["media_id"] == media_id)
    assert entry["processed"]["duration"] == 12.0


def test_photo_entry_has_no_duration(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_media(tmp_path, seam, store, filename="pic.jpg")
    package = seam.get_active_package()
    manifest = json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )
    entry = next(e for e in manifest["media"] if e["media_id"] == media_id)
    assert "duration" not in entry["processed"]


def test_finalize_clears_render_revision(tmp_path):
    store, seam = make_seam(tmp_path)
    seam.get_or_create_active_package()
    status = seam.start_upload("a.jpg", "image/jpeg", 100)
    seam.append_upload_range(status.upload_id, 0, 100, sha(b"x" * 100), b"x" * 100)
    seam.complete_upload(status.upload_id)
    job = seam.claim_next_job()
    assert job is not None
    package = seam.get_active_package()
    manifest_path = tmp_path / package.folder_name / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam._media = StubMediaProcessor()
    seam.process_job(job.job_id)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["render_revision"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_montage.py -v`
Expected: FAIL — `processed.duration` absent; `render_revision` not cleared.

- [ ] **Step 3: Add duration probing to the video processor**

In `dojo-core/src/dojo/adapters/media.py`, add a static method after `_probe`:
```python
    @staticmethod
    def _probe_duration(path: Path) -> float:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise MediaValidationError(
                f"could not probe duration: {result.stderr.strip()}"
            )
        import json as _json

        duration = _json.loads(result.stdout).get("format", {}).get("duration")
        if duration is None:
            raise MediaValidationError("could not read video duration")
        return float(duration)
```
In `_process_video`, after the output `probe` validation and before the `return`, add:
```python
        duration = self._probe_duration(processed_path)
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed_path,
            content_type="video/mp4",
            size_bytes=processed_path.stat().st_size,
            duration=duration,
        )
```
(replacing the existing `return ProcessedMedia(...)` block in `_process_video`).

- [ ] **Step 4: Add duration to `StubMediaProcessor`**

In `dojo-core/src/dojo/adapters/stubs.py`, change the constructor signature and `process`:
```python
    def __init__(
        self,
        *,
        content_type: str = "image/jpeg",
        fail_reason: str | None = None,
        duration: float | None = None,
    ) -> None:
        self.calls: list[tuple[object, Path]] = []
        self.content_type = content_type
        self.fail_reason = fail_reason
        self.duration = duration
```
In `process`, pass duration to `ProcessedMedia`:
```python
        return ProcessedMedia(
            original_path=original_path,
            processed_path=processed,
            content_type=self.content_type,
            size_bytes=processed.stat().st_size,
            dimensions=(100, 100),
            duration=self.duration,
        )
```

- [ ] **Step 5: Store duration and clear `render_revision` in `finalize_media`**

In `dojo-core/src/dojo/publishing.py`, `finalize_media` builds the `processed` dict. Replace:
```python
            processed={
                "path": f"media/{media_id}/processed{processed_ext}",
                "content_type": processed.content_type,
                "size_bytes": processed.size_bytes,
            },
```
with:
```python
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
```
Immediately after loading the manifest (before appending the entry), clear the render revision. Locate the line `manifest = json.loads(manifest_path.read_text(encoding="utf-8"))` inside `finalize_media` (there are several `manifest = json.loads(...)` calls; use the one in `finalize_media` guarded by `upload.conflict_decision`). Add right after it:
```python
        manifest["render_revision"] = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_montage.py -v`
Expected: PASS. Fix any import/mismatch inline.

- [ ] **Step 7: Extend the real-video duration test**

In `dojo-core/tests/test_media_processor.py`, `test_video_transcoded_to_h264_aac` — after the `probe.stdout` assertion, add:
```python
    assert out.duration is not None
    assert out.duration > 0.0
```

- [ ] **Step 8: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src/dojo/adapters/media.py dojo-core/src/dojo/adapters/stubs.py dojo-core/src/dojo/publishing.py dojo-core/tests/test_montage.py dojo-core/tests/test_media_processor.py; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/adapters/media.py dojo-core/src/dojo/adapters/stubs.py dojo-core/src/dojo/publishing.py dojo-core/tests/test_montage.py dojo-core/tests/test_media_processor.py
git commit -m "feat(dojo-core): capture per-clip video duration and clear stale render (#10)"
```

---

### Task 2: Models and exceptions for the montage seam

**Files:**
- Modify: `dojo-core/src/dojo/exceptions.py`
- Modify: `dojo-core/src/dojo/model.py`
- Modify: `dojo-core/src/dojo/__init__.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (imported by Task 3 and Task 4):
  - Exceptions `MontageDurationExceeded(DojoError)`, `MontageTrimInvalid(DojoError)`, `MontageOrderInvalid(DojoError)`.
  - `MontageLimits(max_duration_seconds: float, photo_duration_seconds: float)`.
  - `MontageClip(media_id, filename, content_type, is_video, source_duration=None, effective_duration=0.0)`.
  - `MontageStatus(order, trims, clips, combined_duration, max_duration_seconds, over_limit, required_action=None)`.
  - Exported from `dojo/__init__.py`.

- [ ] **Step 1: Add exceptions**

Append to `dojo-core/src/dojo/exceptions.py`:
```python
class MontageOrderInvalid(DojoError):
    pass


class MontageTrimInvalid(DojoError):
    pass


class MontageDurationExceeded(DojoError):
    pass
```

- [ ] **Step 2: Add models**

Append to `dojo-core/src/dojo/model.py` (after `UploadLimits`):
```python
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
```

- [ ] **Step 3: Export from `__init__.py`**

Add to the `from dojo.exceptions import (...)` block: `MontageDurationExceeded`, `MontageOrderInvalid`, `MontageTrimInvalid`. Add to the `from dojo.model import (...)` block: `MontageClip`, `MontageLimits`, `MontageStatus`. Add all six names to `__all__`.

- [ ] **Step 4: Typecheck, full suite, commit**

Run: `uv run --project dojo-core mypy dojo-core/src/dojo; uv run --project dojo-core pytest dojo-core/tests -v`
Expected: pass

```bash
git add dojo-core/src/dojo/exceptions.py dojo-core/src/dojo/model.py dojo-core/src/dojo/__init__.py
git commit -m "feat(dojo-core): montage models and exceptions (#10)"
```

---

### Task 3: Seam — set_order, set_trims, montage status

**Files:**
- Modify: `dojo-core/src/dojo/publishing.py`
- Modify: `dojo-core/tests/test_montage.py`

**Interfaces:**
- Consumes: Task 1 `finalize_media` duration storage + render clear; Task 2 `MontageLimits`, `MontageClip`, `MontageStatus`, `MontageOrderInvalid`, `MontageTrimInvalid`, `MontageDurationExceeded`; existing `_load_manifest`, `_write_manifest`, `_require_active_package`, `_media_in_completed`.
- Produces:
  - `get_montage_limits() -> MontageLimits`
  - `get_montage_status() -> MontageStatus`
  - `set_order(order: list[str], requester: str | None = None) -> MontageStatus`
  - `set_trims(trims: dict, requester: str | None = None) -> MontageStatus`
  - private `_clip_duration(entry, trims, photo_duration) -> float` and `_combined_duration(order, trims) -> float`.

- [ ] **Step 1: Write the failing tests**

Append to `dojo-core/tests/test_montage.py` (keep Task 1 helpers):
```python
from dojo import (
    MediaNotFound,
    MontageDurationExceeded,
    MontageOrderInvalid,
    MontageTrimInvalid,
)


def load_manifest(tmp_path, seam):
    package = seam.get_active_package()
    return json.loads(
        (tmp_path / package.folder_name / "manifest.json").read_text(encoding="utf-8")
    )


def test_set_order_persists_permutation(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_media(tmp_path, seam, store, filename="a.jpg")
    second = finalize_media(tmp_path, seam, store, filename="b.jpg")
    third = finalize_media(tmp_path, seam, store, filename="c.jpg")

    seam.set_order([third, first, second], requester="7")

    assert load_manifest(tmp_path, seam)["order"] == [third, first, second]
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "montage.order_changed"
    assert seam.list_audit()[0].actor == "7"


def test_set_order_requires_exact_finalized_set(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_media(tmp_path, seam, store, filename="a.jpg")
    second = finalize_media(tmp_path, seam, store, filename="b.jpg")

    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first])  # missing second
    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first, second, second])  # duplicate
    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first, second, "unknown"])  # unknown id


def test_set_order_rejects_removed_ids(tmp_path):
    store, seam = make_seam(tmp_path)
    first = finalize_media(tmp_path, seam, store, filename="a.jpg")
    second = finalize_media(tmp_path, seam, store, filename="b.jpg")
    seam.remove_media(second)

    with pytest.raises(MontageOrderInvalid):
        seam.set_order([first, second])


def test_set_trims_persists_and_requires_video(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    photo = finalize_media(tmp_path, seam, store, filename="pic.jpg")

    seam.set_trims({video: {"start": 1.0, "end": 6.0}}, requester="8")

    manifest = load_manifest(tmp_path, seam)
    assert manifest["trims"] == {video: {"start": 1.0, "end": 6.0}}
    actions = [e.action for e in seam.list_audit()]
    assert actions[0] == "montage.trim_changed"
    assert seam.list_audit()[0].actor == "8"

    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({photo: {"start": 0.0, "end": 1.0}})


def test_set_trims_requires_video_duration_known(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )

    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({video: {"start": 9.0, "end": 11.0}})  # beyond duration
    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({video: {"start": 5.0, "end": 5.0}})  # start == end
    with pytest.raises(MontageTrimInvalid):
        seam.set_trims({video: {"start": -1.0, "end": 2.0}})  # negative start


def test_set_trims_unknown_media_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    finalize_media(tmp_path, seam, store, filename="a.jpg")
    with pytest.raises(MediaNotFound):
        seam.set_trims({"nope": {"start": 0.0, "end": 1.0}})


def test_combined_duration_math(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    photo = finalize_media(tmp_path, seam, store, filename="pic.jpg")

    seam.set_trims({video: {"start": 1.0, "end": 6.0}})
    status = seam.get_montage_status()
    # photo default 3.0 + video (10 - (6-1)) = 5.0
    assert abs(status.combined_duration - 8.0) < 1e-6


def test_over_limit_order_rejected_with_action(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 5.0, updated_at=FIXED_AT)
    a = finalize_media(tmp_path, seam, store, filename="a.jpg")
    b = finalize_media(tmp_path, seam, store, filename="b.jpg")
    # photo default 3.0 each -> 6.0 > 5.0

    with pytest.raises(MontageDurationExceeded) as exc_info:
        seam.set_order([a, b])
    assert "trim or remove" in str(exc_info.value)
    assert "1.0" in str(exc_info.value)
    assert load_manifest(tmp_path, seam)["order"] == [a, b]  # unchanged (append order)


def test_over_limit_trims_rejected_and_unchanged(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 6.0, updated_at=FIXED_AT)
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    seam.set_trims({video: {"start": 0.0, "end": 9.0}})  # effective 1.0s, valid
    # Shrinking the trim window lengthens the clip; pushing effective past 6s.
    with pytest.raises(MontageDurationExceeded):
        seam.set_trims({video: {"start": 0.0, "end": 1.0}})  # effective 9.0s > 6s
    manifest = load_manifest(tmp_path, seam)
    assert manifest["trims"] == {video: {"start": 0.0, "end": 9.0}}  # unchanged


def test_order_and_trim_edits_clear_render_revision(tmp_path):
    store, seam = make_seam(tmp_path)
    a = finalize_media(tmp_path, seam, store, filename="a.jpg")
    video = finalize_media(
        tmp_path, seam, store, filename="clip.mp4",
        content_type="video/mp4", duration=10.0,
    )
    manifest_path = tmp_path / seam.get_active_package().folder_name / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam.set_order([video, a])
    assert load_manifest(tmp_path, seam)["render_revision"] is None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["render_revision"] = "rev-2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    seam.set_trims({video: {"start": 0.0, "end": 5.0}})
    assert load_manifest(tmp_path, seam)["render_revision"] is None


def test_get_montage_status_reports_over_limit_and_action(tmp_path):
    store, seam = make_seam(tmp_path)
    store.set("montage.max_duration_seconds", 2.0, updated_at=FIXED_AT)
    finalize_media(tmp_path, seam, store, filename="a.jpg")
    status = seam.get_montage_status()
    assert status.over_limit is True
    assert status.required_action is not None
    assert "trim or remove" in status.required_action


def test_montage_mutation_on_completed_package_raises(tmp_path):
    store, seam = make_seam(tmp_path)
    media_id = finalize_media(tmp_path, seam, store, filename="a.jpg")
    seam.complete_active_package(requester="9")
    with pytest.raises(PackageCompleted):
        seam.set_order([media_id])
    with pytest.raises(PackageCompleted):
        seam.set_trims({media_id: {"start": 0.0, "end": 1.0}})


def test_montage_without_active_package_raises(tmp_path):
    _, seam = make_seam(tmp_path)
    with pytest.raises(NoActivePackage):
        seam.set_order([])
    with pytest.raises(NoActivePackage):
        seam.set_trims({})
    with pytest.raises(NoActivePackage):
        seam.get_montage_status()
```

Note: `FIXED_AT` must be imported in `test_montage.py`. Add `from dojo.testing import FIXED_AT, FakeClock` to the imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_montage.py -v`
Expected: FAIL — methods missing on `DojoPublishing`.

- [ ] **Step 3: Implement the seam**

In `dojo-core/src/dojo/publishing.py`:
- extend the `from dojo.exceptions import (...)` block with `MontageDurationExceeded`, `MontageOrderInvalid`, `MontageTrimInvalid`.
- extend the `from dojo.model import (...)` block with `MontageClip`, `MontageLimits`, `MontageStatus`.
- add module constants after `STALE_TTL`:
```python
DEFAULT_MAX_MONTAGE_SECONDS = 90.0
DEFAULT_PHOTO_SECONDS = 3.0
```
- Replace the stub `set_order` (currently `def set_order(self, *args: object, **kwargs: object) -> None: raise NotImplementedError`) with real methods. Place them after `_write_manifest`:
```python
    def get_montage_limits(self) -> MontageLimits:
        max_seconds = self._settings.get("montage.max_duration_seconds") or DEFAULT_MAX_MONTAGE_SECONDS
        photo_seconds = self._settings.get("montage.photo_duration_seconds") or DEFAULT_PHOTO_SECONDS
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
        manifest = self._load_manifest(package)
        finalized = [e.get("media_id") for e in manifest.get("media", []) if e.get("status") == "finalized"]
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
                raise MontageTrimInvalid(f"media {media_id} is not a video; trims apply to videos only")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project dojo-core pytest dojo-core/tests/test_montage.py -v`
Expected: PASS. Walk the file and fix any test/implementation mismatches inline (e.g. `FIXED_AT` import, exception semantics).

- [ ] **Step 5: Update the design doc exception list**

In `docs/superpowers/specs/2026-08-17-montage-ordering-trims-duration-design.md`, add `MontageOrderInvalid(DojoError)` to the Exceptions section (next to `MontageDurationExceeded` and `MontageTrimInvalid`).

- [ ] **Step 6: Lint, typecheck, full suite, commit**

Run: `uv run --project dojo-core ruff check dojo-core/src/dojo/publishing.py dojo-core/tests/test_montage.py; uv run --project dojo-core mypy dojo-core/src/dojo`
Expected: no findings
Run: `uv run --project dojo-core pytest dojo-core/tests -v`
Expected: all pass

```bash
git add dojo-core/src/dojo/publishing.py dojo-core/tests/test_montage.py docs/superpowers/specs/2026-08-17-montage-ordering-trims-duration-design.md
git commit -m "feat(dojo-core): montage order, trims, and duration limits (#10)"
```

---

### Task 4: FastAPI routes and contract tests

**Files:**
- Modify: `backend/src/backend/routes/packages.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 2 `MontageOrderInvalid`, `MontageTrimInvalid`, `MontageDurationExceeded`; Task 3 `set_order`, `set_trims`, `get_montage_status`; `MontageStatus.to_dict()`.
- Produces: `PUT /api/packages/active/order`, `PUT /api/packages/active/trims`, `GET /api/packages/active/montage`.

- [ ] **Step 1: Write the failing contract tests**

Append to `backend/tests/test_api.py`:
```python
def test_montage_routes_require_auth(tmp_path: Path) -> None:
    client, _, _, _ = make_app(tmp_path)
    assert client.get("/api/packages/active/montage").status_code == 401
    assert client.put("/api/packages/active/order", json={"order": []}).status_code == 401
    assert client.put("/api/packages/active/trims", json={"trims": {}}).status_code == 401


def test_set_order_via_api(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="a.jpg")
    media_id = media_id_of(tmp_path, publishing)

    resp = client.put(
        "/api/packages/active/order",
        headers=bearer(token),
        json={"order": [media_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["order"] == [media_id]
    assert resp.json()["over_limit"] is False


def test_set_order_over_limit_409_via_api(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    publishing._settings.set("montage.max_duration_seconds", 2.0, updated_at=FakeClock().now())
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="a.jpg")
    media_id = media_id_of(tmp_path, publishing)

    resp = client.put(
        "/api/packages/active/order",
        headers=bearer(token),
        json={"order": [media_id]},
    )
    assert resp.status_code == 409
    assert "trim or remove" in resp.json()["detail"]


def test_get_montage_via_api(tmp_path: Path) -> None:
    client, publishing, pairing, _ = make_app(tmp_path)
    publishing._media = StubMediaProcessor()
    token = pair_device(client, pairing)
    finalize_via_api(client, publishing, token, filename="a.jpg")

    resp = client.get("/api/packages/active/montage", headers=bearer(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["combined_duration"] == 3.0
    assert len(body["clips"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/test_api.py -k montage -v`
Expected: FAIL — routes missing (404).

- [ ] **Step 3: Add routes to `packages.py`**

In `backend/src/backend/routes/packages.py`:
- extend the `from dojo import (...)` block with `MontageDurationExceeded`, `MontageOrderInvalid`, `MontageTrimInvalid`.
- add Pydantic bodies after `DownloadOut`:
```python
class OrderIn(BaseModel):
    order: list[str]


class TrimsIn(BaseModel):
    trims: dict[str, dict[str, float]]
```
- add to `_MUTATION_STATUS`:
```python
    MontageOrderInvalid: 422,
    MontageTrimInvalid: 422,
    MontageDurationExceeded: 409,
```
- add routes after `restore_media`:
```python
@router.get("/active/montage", response_model=dict[str, object])
def get_montage(
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.get_montage_status().to_dict()
    except NoActivePackage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/active/order", response_model=dict[str, object])
def set_order(
    body: OrderIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.set_order(body.order, requester=str(client.id)).to_dict()
    except (NoActivePackage, MediaNotFound, PackageCompleted) as exc:
        _map_mutation_error(exc)
    except MontageOrderInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MontageDurationExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return publishing.get_montage_status().to_dict()


@router.put("/active/trims", response_model=dict[str, object])
def set_trims(
    body: TrimsIn,
    client: Client = Depends(get_current_client),
    publishing: DojoPublishing = Depends(get_publishing),
) -> dict[str, object]:
    try:
        return publishing.set_trims(body.trims, requester=str(client.id)).to_dict()
    except (NoActivePackage, MediaNotFound, PackageCompleted) as exc:
        _map_mutation_error(exc)
    except MontageTrimInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MontageDurationExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return publishing.get_montage_status().to_dict()
```
Note: the two `except (NoActivePackage, ...)` blocks call `_map_mutation_error(exc)` which always raises an `HTTPException` when the exception type is in `_MUTATION_STATUS`, so the trailing `return publishing.get_montage_status().to_dict()` is unreachable-but-required by mypy for the exception path. Keep it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest backend/tests/test_api.py -k montage -v`
Expected: PASS.

- [ ] **Step 5: Lint, typecheck, full suite, commit**

Run: `uv run --project backend ruff check backend/src backend/tests; uv run --project backend mypy backend/src/backend`
Expected: no findings
Run: `uv run --project backend pytest backend/tests -v`
Expected: all pass

```bash
git add backend/src/backend/routes/packages.py backend/tests/test_api.py
git commit -m "feat(backend): montage order, trims, and status routes (#10)"
```
