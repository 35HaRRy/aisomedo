"""Recovery trust boundaries; only Docker calls are doubled."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def backup_cli(monkeypatch):
    ops = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(ops))
    script = ops / "backup.py"
    assert script.exists(), "encrypted recovery CLI is missing"
    spec = importlib.util.spec_from_file_location("backup_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def age_keys(tmp_path):
    if not shutil.which("age") or not shutil.which("age-keygen"):
        if os.environ.get("REQUIRE_BACKUP_INTEGRATION") == "1":
            pytest.fail("required recovery verification needs age and age-keygen")
        pytest.skip("install age for authenticated encryption tests")
    identity = tmp_path / "identity.txt"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    recipient = subprocess.check_output(["age-keygen", "-y", str(identity)]).decode().strip()
    return identity, recipient


def payload(tmp_path, cli):
    root = tmp_path / "payload"
    (root / "config").mkdir(parents=True)
    (root / "media/nested").mkdir(parents=True)
    (root / "media/empty").mkdir()
    (root / "database.dump").write_bytes(b"PGDMP fixture")
    (root / "config/production.env").write_text("SIGNED_URL_SECRET=fixture-only\n")
    (root / "media/nested/binary.bin").write_bytes(b"\x00\xfforiginal")
    state = {"sha": "1" * 40, "mode": "existing-proxy", "monitoring": False,
             "origin": "https://fixture.invalid"}
    (root / "current.json").write_text(json.dumps(state))
    images = {s: f"ghcr.io/fixture/{s}@sha256:{'a' * 64}"
              for s in ("backend", "worker", "gateway")}
    cli.deploy.build_bundle(state["sha"], images, root / "release")
    files = {}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        files[name] = ({"type": "directory"} if path.is_dir() else
                       {"type": "file", "size": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"version": 1, "created_at": "2026-10-14T00:00:00+00:00", "state": state,
                "database": {"image": "sha256:" + "b" * 64, "major": "18",
                             "tables": [], "schema_version": []},
                "files": files, "credentials": {}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    archive = tmp_path / "payload.tar"
    with tarfile.open(archive, "w") as tar:
        for path in sorted(root.rglob("*")):
            tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    return root, archive, manifest


def test_archive_roundtrip(backup_cli, tmp_path):
    _, archive, manifest = payload(tmp_path, backup_cli)
    target = tmp_path / "extracted"
    assert backup_cli.validate_archive(archive, target) == manifest
    assert (target / "media/nested/binary.bin").read_bytes() == b"\x00\xfforiginal"
    assert (target / "media/empty").is_dir()


@pytest.mark.parametrize("name,kind", [
    ("../outside", "file"), ("/absolute", "file"), ("media/a/../alias", "file"),
    ("media/link", "symlink"), ("media/hard", "hardlink"), ("media/fifo", "fifo"),
    ("media/back\\slash", "file"), ("manifest.json", "file"),
])
def test_unsafe_archive_rejected(backup_cli, tmp_path, name, kind):
    _, archive, _ = payload(tmp_path, backup_cli)
    with tarfile.open(archive, "a") as tar:
        entry = tarfile.TarInfo(name)
        entry.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                      "fifo": tarfile.FIFOTYPE}.get(kind, tarfile.REGTYPE)
        entry.linkname = "../../outside" if kind != "file" else ""
        tar.addfile(entry, io.BytesIO(b""))
    with pytest.raises(ValueError):
        backup_cli.validate_archive(archive, tmp_path / "extracted")
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("mutation", ["version", "missing", "extra", "digest", "size", "state"])
def test_manifest_inventory_and_checksums(backup_cli, tmp_path, mutation):
    root, archive, manifest = payload(tmp_path, backup_cli)
    if mutation == "version":
        manifest["version"] = 99
    elif mutation == "missing":
        (root / "database.dump").unlink()
    elif mutation == "extra":
        (root / "media/unknown").write_bytes(b"unlisted")
    elif mutation == "digest":
        (root / "media/nested/binary.bin").write_bytes(b"corrupt")
    elif mutation == "size":
        manifest["files"]["database.dump"]["size"] = 2**60
    else:
        manifest["state"]["sha"] = "../escape"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with tarfile.open(archive, "w") as tar:
        for path in root.rglob("*"):
            tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    with pytest.raises((ValueError, RuntimeError)):
        backup_cli.validate_archive(archive, tmp_path / "extracted")


def test_archive_space_limit(backup_cli, tmp_path, monkeypatch):
    _, archive, _ = payload(tmp_path, backup_cli)
    usage = shutil._ntuple_diskusage(100, 99, 1)
    monkeypatch.setattr(backup_cli.shutil, "disk_usage", lambda _: usage)
    with pytest.raises(RuntimeError, match="space"):
        backup_cli.validate_archive(archive, tmp_path / "extracted")


@pytest.mark.parametrize("mutation", ["wrong-key", "changed", "truncated"])
def test_wrong_identity_and_tampered_ciphertext(backup_cli, tmp_path, age_keys, mutation):
    identity, recipient = age_keys
    plain = tmp_path / "input"
    plain.write_bytes(b"private" * 20000)
    encrypted = tmp_path / "backup.age"
    backup_cli.encrypt_archive(plain, recipient, encrypted)
    if mutation == "wrong-key":
        identity = tmp_path / "other-key.txt"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    else:
        data = bytearray(encrypted.read_bytes())
        if mutation == "changed":
            data[-30] ^= 1
        else:
            del data[-20:]
        encrypted.write_bytes(data)
    with pytest.raises(RuntimeError):
        backup_cli.decrypt_archive(encrypted, identity, tmp_path / "decrypted")
    assert not (tmp_path / "decrypted").exists()


def test_output_never_overwritten(backup_cli, tmp_path, age_keys):
    identity, recipient = age_keys
    plain = tmp_path / "input"
    plain.write_bytes(b"original")
    encrypted = tmp_path / "backup.age"
    backup_cli.encrypt_archive(plain, recipient, encrypted)
    backup_cli.decrypt_archive(encrypted, identity, tmp_path / "decrypted")
    assert (tmp_path / "decrypted").read_bytes() == b"original"
    original = encrypted.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        backup_cli.encrypt_archive(plain, recipient, encrypted)
    assert encrypted.read_bytes() == original
