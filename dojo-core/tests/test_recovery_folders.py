from __future__ import annotations

import json
from pathlib import Path

from dojo import DojoPublishing, InMemoryStore
from dojo.adapters.stubs import StubMetaPublisher, StubNotifier, StubSignedUrlStore
from dojo.testing import FakeClock


def make_seam(tmp_path: Path, **overrides):
    store = InMemoryStore()
    seam = DojoPublishing(
        packages=store,
        audit=store,
        uploads=store,
        jobs=store,
        settings=store,
        media_root=tmp_path,
        clock=FakeClock(),
        meta=StubMetaPublisher(),
        notifier=overrides.pop("notifier", StubNotifier()),
        signed_urls=StubSignedUrlStore(),
        **overrides,
    )
    return store, seam


def write_open_folder(root: Path, name: str, *, marker: str = "m") -> Path:
    folder = root / name
    (folder / "media").mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({"media": [], "order": []}), encoding="utf-8")
    (folder / "media" / "keep.txt").write_text(marker, encoding="utf-8")
    return folder


def test_newest_unsuffixed_wins_older_renamed_recovered(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    older = write_open_folder(tmp_path, "05-08-2026 14-30", marker="old")
    newer = write_open_folder(tmp_path, "06-08-2026 14-30", marker="new")

    result = seam.repair_open_folders(requester="system")

    assert result["active"] == "06-08-2026 14-30"
    assert result["recovered"] == ["05-08-2026 14-30-recovered"]
    assert (tmp_path / "06-08-2026 14-30").is_dir()
    recovered = tmp_path / "05-08-2026 14-30-recovered"
    assert recovered.is_dir()
    assert (recovered / "media" / "keep.txt").read_text(encoding="utf-8") == "old"
    assert not older.exists()
    assert newer.is_dir()
    actions = [e.action for e in seam.list_audit()]
    assert "package.recovery" in actions


def test_single_open_folder_needs_no_repair(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    write_open_folder(tmp_path, "06-08-2026 14-30")

    result = seam.repair_open_folders()

    assert result["active"] == "06-08-2026 14-30"
    assert result["recovered"] == []


def test_unparseable_folder_never_wins(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    write_open_folder(tmp_path, "06-08-2026 14-30")
    write_open_folder(tmp_path, "notes-scratch")

    result = seam.repair_open_folders()

    assert result["active"] == "06-08-2026 14-30"


def _seed_active_with_conflict_target(tmp_path: Path, seam) -> None:
    import hashlib

    from dojo.adapters.stubs import StubMediaProcessor

    seam._media = StubMediaProcessor()
    seam.ensure_active_package()
    body = b"x" * 100
    status = seam.start_upload("photo.jpg", "image/jpeg", len(body))
    seam.append_upload_range(status.upload_id, 0, len(body), hashlib.sha256(body).hexdigest(), body)
    seam.complete_upload(status.upload_id)
    claimed = seam.claim_next_job()
    assert claimed is not None
    seam.process_job(claimed.job_id)


def _seed_recovered_folder(tmp_path: Path, name: str, files: dict[str, bytes]) -> Path:
    folder = tmp_path / name
    media_dir = folder / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    manifest_media = []
    for idx, (filename, body) in enumerate(files.items()):
        media_id = f"rec-{idx}"
        entry_dir = media_dir / media_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / filename).write_bytes(body)
        manifest_media.append(
            {
                "media_id": media_id,
                "filename": filename,
                "content_type": "image/jpeg",
                "size_bytes": len(body),
                "uploaded_at": "2026-08-06T14:30:00+03:00",
                "status": "finalized",
                "processed": {},
            }
        )
    manifest = {"media": manifest_media, "order": [m["media_id"] for m in manifest_media]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_import_goes_through_conflict_workflow(tmp_path: Path) -> None:
    from dojo.adapters.stubs import StubMediaProcessor

    _, seam = make_seam(tmp_path)
    seam._media = StubMediaProcessor()
    _seed_active_with_conflict_target(tmp_path, seam)
    _seed_recovered_folder(
        tmp_path, "05-08-2026 14-30-recovered", {"photo.jpg": b"y" * 50, "fresh.jpg": b"z" * 60}
    )

    result = seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")

    assert result["imported"] == 2
    by_name = {u["filename"]: u["status"] for u in result["uploads"]}
    assert by_name["photo.jpg"] == "conflict"
    assert by_name["fresh.jpg"] in ("receiving", "conflict", "queued")
    actions = [e.action for e in seam.list_audit()]
    assert "package.recovered_import" in actions


def test_resolved_prevents_reimport(tmp_path: Path) -> None:
    import pytest

    from dojo import MediaNotFound

    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    _seed_recovered_folder(tmp_path, "05-08-2026 14-30-recovered", {"a.jpg": b"q" * 10})

    resolved = seam.mark_recovered_resolved("05-08-2026 14-30-recovered", requester="7")

    assert resolved == "05-08-2026 14-30-resolved"
    assert (tmp_path / resolved).is_dir()
    assert seam.list_recovered_folders() == []
    with pytest.raises(MediaNotFound):
        seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")
    with pytest.raises(MediaNotFound):
        seam.import_recovered_media(resolved, requester="7")
