from __future__ import annotations

import json
from pathlib import Path

import pytest
from dojo import DojoPublishing, InMemoryStore, MediaNotFound
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


@pytest.mark.parametrize("with_package", [False, True])
def test_repair_preserves_shared_branding_assets(tmp_path: Path, with_package: bool) -> None:
    _, seam = make_seam(tmp_path)
    logo = tmp_path / "branding" / "assets" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"dojo-logo")
    if with_package:
        write_open_folder(tmp_path, "06-08-2026 14-30")

    result = seam.repair_open_folders()

    assert logo.is_file(), "startup recovery must not move shared branding assets"
    assert logo.read_bytes() == b"dojo-logo"
    assert result == {"active": "06-08-2026 14-30" if with_package else None, "recovered": []}
    assert not (tmp_path / "branding" / "manifest.json").exists()
    assert not seam.list_recovered_folders()
    if not with_package:
        assert seam.get_active_package() is None


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


def write_bom_folder(root: Path, name: str) -> Path:
    """Simulate Windows PowerShell 5.1 `Set-Content -Encoding utf8`, which emits a BOM."""
    folder = root / name
    (folder / "media").mkdir(parents=True, exist_ok=True)
    body = json.dumps({"media": [], "order": []}).encode("utf-8")
    (folder / "manifest.json").write_bytes(b"\xef\xbb\xbf" + body)
    return folder


def test_bom_manifest_does_not_break_repair(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    write_open_folder(tmp_path, "05-08-2026 14-30")
    write_bom_folder(tmp_path, "06-08-2026 14-30")

    result = seam.repair_open_folders()

    assert result["active"] == "06-08-2026 14-30"
    assert result["recovered"] == ["05-08-2026 14-30-recovered"]


def test_bom_manifest_does_not_break_evaluate_due_work(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    folder = write_bom_folder(tmp_path, "06-08-2026 14-30")
    seam.repair_open_folders()

    seam.evaluate_due_work()  # must not raise

    assert (folder / "manifest.json").read_bytes().startswith(b"\xef\xbb\xbf")


def test_bom_recovered_manifest_imports(tmp_path: Path) -> None:
    from dojo.adapters.stubs import StubMediaProcessor

    _, seam = make_seam(tmp_path)
    seam._media = StubMediaProcessor()
    seam.ensure_active_package()
    folder = _seed_recovered_folder(tmp_path, "05-08-2026 14-30-recovered", {"a.jpg": b"q" * 10})
    raw = (folder / "manifest.json").read_bytes()
    (folder / "manifest.json").write_bytes(b"\xef\xbb\xbf" + raw)

    result = seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")

    assert result["imported"] == 1


def test_folder_name_taken_by_settled_row_never_wins(tmp_path: Path) -> None:
    """A completed row holding the name must not be re-activated (unique folder_name)."""
    from dojo.model import Package
    from dojo.testing import FIXED_AT

    store, seam = make_seam(tmp_path)
    write_open_folder(tmp_path, "05-08-2026 14-30")
    write_open_folder(tmp_path, "06-08-2026 14-30")
    store.create(
        Package(id=0, folder_name="06-08-2026 14-30", created_at=FIXED_AT, status="completed")
    )

    result = seam.repair_open_folders()

    assert result["active"] == "05-08-2026 14-30"
    assert result["recovered"] == ["06-08-2026 14-30-recovered"]


def test_collision_suffixed_folders_are_settled_not_open(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    write_open_folder(tmp_path, "06-08-2026 14-30")
    dup = tmp_path / "05-08-2026 14-30-recovered (2)"
    (dup / "media").mkdir(parents=True, exist_ok=True)
    (dup / "manifest.json").write_text(json.dumps({"media": [], "order": []}), encoding="utf-8")

    result = seam.repair_open_folders()

    assert result["active"] == "06-08-2026 14-30"
    assert result["recovered"] == []
    assert dup.is_dir()
    assert "05-08-2026 14-30-recovered (2)" in seam.list_recovered_folders()


def test_repair_defers_db_when_publishing_in_progress(tmp_path: Path) -> None:
    from dojo.model import Package
    from dojo.testing import FIXED_AT

    store, seam = make_seam(tmp_path)
    pub_folder = tmp_path / "06-08-2026 13-30-publishing"
    pub_folder.mkdir(parents=True, exist_ok=True)
    (pub_folder / "manifest.json").write_text(json.dumps({"media": []}), encoding="utf-8")
    store.create(
        Package(
            id=0,
            folder_name="06-08-2026 13-30-publishing",
            created_at=FIXED_AT,
            status="publishing",
        )
    )
    write_open_folder(tmp_path, "05-08-2026 14-30")
    write_open_folder(tmp_path, "06-08-2026 14-30")

    result = seam.repair_open_folders()

    assert result["active"] == "06-08-2026 14-30"
    assert seam.get_active_package() is None
    assert (tmp_path / "05-08-2026 14-30-recovered").is_dir()


def test_all_unparseable_newest_mtime_wins(tmp_path: Path) -> None:
    import os
    import time

    _, seam = make_seam(tmp_path)
    old_dir = write_open_folder(tmp_path, "scratch-old")
    write_open_folder(tmp_path, "scratch-new")
    ancient = time.time() - 1000
    os.utime(old_dir, (ancient, ancient))

    result = seam.repair_open_folders()

    assert result["active"] == "scratch-new"


def test_single_folder_db_mismatch_audited(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    write_open_folder(tmp_path, "07-08-2026 14-30")

    result = seam.repair_open_folders()

    assert result["active"] == "07-08-2026 14-30"
    assert seam.get_active_package() is not None
    assert seam.get_active_package().folder_name == "07-08-2026 14-30"
    actions = [e.action for e in seam.list_audit()]
    assert "package.recovery" in actions


def test_import_isolates_missing_files_and_audits(tmp_path: Path) -> None:
    from dojo.adapters.stubs import StubMediaProcessor

    _, seam = make_seam(tmp_path)
    seam._media = StubMediaProcessor()
    seam.ensure_active_package()
    folder = _seed_recovered_folder(tmp_path, "05-08-2026 14-30-recovered", {"good.jpg": b"g" * 20})
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["media"].append(
        {
            "media_id": "rec-ghost",
            "filename": "ghost.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 10,
            "uploaded_at": "2026-08-06T14:30:00+03:00",
            "status": "finalized",
            "processed": {},
        }
    )
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")

    assert result["imported"] == 1
    assert [f["filename"] for f in result["failed"]] == ["ghost.jpg"]
    actions = [e.action for e in seam.list_audit()]
    assert "package.recovered_import" in actions


def test_import_empty_recovered_audits_zero(tmp_path: Path) -> None:
    _, seam = make_seam(tmp_path)
    seam.ensure_active_package()
    _seed_recovered_folder(tmp_path, "05-08-2026 14-30-recovered", {})

    result = seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")

    assert result == {
        "folder": "05-08-2026 14-30-recovered",
        "imported": 0,
        "uploads": [],
        "failed": [],
    }
    assert "package.recovered_import" in [e.action for e in seam.list_audit()]


def test_reimport_without_resolve_duplicates_documented(tmp_path: Path) -> None:
    from dojo.adapters.stubs import StubMediaProcessor

    _, seam = make_seam(tmp_path)
    seam._media = StubMediaProcessor()
    seam.ensure_active_package()
    _seed_recovered_folder(tmp_path, "05-08-2026 14-30-recovered", {"a.jpg": b"q" * 10})

    first = seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")
    second = seam.import_recovered_media("05-08-2026 14-30-recovered", requester="7")

    assert first["imported"] == second["imported"] == 1
    assert first["uploads"][0]["upload_id"] != second["uploads"][0]["upload_id"]
