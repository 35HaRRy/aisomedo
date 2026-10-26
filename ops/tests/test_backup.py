"""Recovery trust boundaries; only Docker calls are doubled."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

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


@pytest.fixture
def installation(backup_cli, tmp_path, monkeypatch):
    root = tmp_path / "install"
    root.mkdir()
    _, archive, manifest = payload(tmp_path, backup_cli)
    (root / "config").mkdir()
    shutil.copyfile(tmp_path / "payload/config/production.env", root / "config/production.env")
    (root / "current.json").write_text(json.dumps(manifest["state"]))
    release = root / "releases" / manifest["state"]["sha"]
    shutil.copytree(tmp_path / "payload/release", release)
    events = []
    info = {"root": root, "state": manifest["state"], "release": release,
            "images": {}, "command": ["docker", "compose"], "config": {},
            "containers": {"backend": ["api"], "worker": ["w1", "w2"], "db": ["db"]},
            "media_volume": "fixture_media", "worker_count": 2}
    stopped = set()

    def external(args, **kwargs):
        events.append(list(args))
        if "ps" in args:
            return "\n".join(info["containers"].get(args[-1], [])).encode()
        if "stop" in args:
            stopped.update(["api", "w1", "w2"])
        if "up" in args:
            stopped.clear()
        return b""

    monkeypatch.setattr(backup_cli.deploy, "installation_lock", lambda _: contextlib.nullcontext())
    monkeypatch.setattr(backup_cli.deploy, "run", external)
    monkeypatch.setattr(backup_cli.deploy, "inspect_container", lambda name, **_: {
        "State": {"Running": name not in stopped}})
    monkeypatch.setattr(backup_cli.deploy, "running", lambda *_, **__: info["containers"])
    monkeypatch.setattr(backup_cli.deploy, "verify_public_health", lambda *_: None)
    monkeypatch.setattr(backup_cli, "read_installation", lambda _: info, raising=False)

    def capture(*_):
        assert stopped == {"api", "w1", "w2"}, "capture must stop all writers first"
        events.append(["capture"])
        return archive

    monkeypatch.setattr(backup_cli, "capture_archive", capture, raising=False)
    return root, info, events, stopped


def test_all_writer_replicas_stopped_before_capture(backup_cli, installation, tmp_path,
                                                   age_keys, monkeypatch):
    root, _, events, stopped = installation
    identity, recipient = age_keys
    # Keep age subprocess real; the deployment subprocess double is Docker-only.
    monkeypatch.setattr(backup_cli, "age_file", lambda source, output, args:
                        _real_age_file(backup_cli, source, output, args))
    backup_cli.backup(root, recipient, tmp_path / "backup.age")
    assert not stopped
    assert events.index(["capture"]) > next(i for i, e in enumerate(events) if "stop" in e)
    start = next(e for e in events if "up" in e)
    assert start[start.index("--scale") + 1] == "worker=2"
    assert "--no-deps" in start
    assert "init" not in start
    result = tmp_path / "restored.tar"
    _real_age_file(backup_cli, tmp_path / "backup.age", result,
                   ["--decrypt", "--identity", str(identity)])
    backup_cli.validate_archive(result, tmp_path / "decoded")


def _real_age_file(cli, source, output, args):
    output.write_bytes(subprocess.check_output(["age", *args, str(source)]))


@pytest.mark.parametrize("failure", ["capture", "signal", "partial-stop"])
def test_backup_failure_and_signal_restart_original_replicas(backup_cli, installation,
                                                              tmp_path, age_keys, monkeypatch,
                                                              failure):
    root, _, events, stopped = installation
    _, recipient = age_keys
    external = backup_cli.deploy.run

    def run(args, **kwargs):
        if "age" == args[0]:
            return subprocess.run(args, stdout=kwargs.get("stdout"), check=True,
                                  capture_output=not kwargs.get("stdout")).stdout or b""
        result = external(args, **kwargs)
        if failure == "partial-stop" and "stop" in args:
            raise RuntimeError("partial stop")
        return result

    monkeypatch.setattr(backup_cli.deploy, "run", run)

    def broken_capture(*_):
        if failure == "signal":
            signal.raise_signal(signal.SIGTERM)
        raise RuntimeError("capture failure")

    monkeypatch.setattr(backup_cli, "capture_archive", broken_capture)
    with pytest.raises(RuntimeError):
        backup_cli.backup(root, recipient, tmp_path / "backup.age")
    assert not stopped
    assert any("up" in e for e in events)
    assert not (tmp_path / "backup.age").exists()


def test_lock_contention_prevents_mutation(backup_cli, installation, tmp_path,
                                          age_keys, monkeypatch):
    root, _, events, _ = installation

    @contextlib.contextmanager
    def locked(_):
        raise RuntimeError("another deployment holds lock")
        yield

    monkeypatch.setattr(backup_cli.deploy, "installation_lock", locked)
    with pytest.raises(RuntimeError, match="lock"):
        backup_cli.backup(root, age_keys[1], tmp_path / "backup.age")
    assert not events


def test_backup_preflight_before_stop(backup_cli, installation, tmp_path,
                                     age_keys, monkeypatch):
    root, _, events, _ = installation
    usage = shutil._ntuple_diskusage(100, 99, 1)
    monkeypatch.setattr(backup_cli.shutil, "disk_usage", lambda _: usage)
    with pytest.raises(RuntimeError, match="space"):
        backup_cli.backup(root, age_keys[1], tmp_path / "backup.age")
    assert not any("stop" in e for e in events)


def test_restart_failure_not_success(backup_cli, installation, tmp_path, age_keys, monkeypatch):
    root, _, _, _ = installation
    monkeypatch.setattr(backup_cli, "age_file", lambda source, output, args:
                        _real_age_file(backup_cli, source, output, args))
    monkeypatch.setattr(backup_cli.deploy, "verify_public_health",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("health failed")))
    with pytest.raises(RuntimeError, match="health"):
        backup_cli.backup(root, age_keys[1], tmp_path / "backup.age")


@pytest.mark.parametrize("oversized_manifest", [False, True])
def test_backup_includes_database_config_credentials_and_all_media(backup_cli, tmp_path,
                                                                  monkeypatch,
                                                                  oversized_manifest):
    root, _, manifest = payload(tmp_path, backup_cli)
    manifest["state"]["monitoring"] = True
    (root / "current.json").write_text(json.dumps(manifest["state"]))
    credential = tmp_path / "external-firebase.json"
    credential.write_bytes(b'{"project_id":"fixture-only"}')
    info = {"root": root, "state": manifest["state"], "release": root / "release",
            "credential": credential, "containers": {"db": ["fixture-db"]},
            "config": {"services": {"db": {"environment": {
                "POSTGRES_USER": "fixture", "POSTGRES_DB": "fixture"}}}}}

    def run(args, **kwargs):
        assert "pg_dump" in args
        kwargs["stdout"].write(b"PGDMP fixture dump")
        return b""

    def export(_installation, _script, *, output):
        with tarfile.open(fileobj=output, mode="w|") as tar:
            for path in [root / "media", *sorted((root / "media").rglob("*"))]:
                tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)

    monkeypatch.setattr(backup_cli.deploy, "run", run)
    monkeypatch.setattr(backup_cli, "volume_helper", export)
    monkeypatch.setattr(backup_cli, "database_metadata", lambda _: manifest["database"])
    staging = tmp_path / "capture"
    staging.mkdir()
    if oversized_manifest:
        manifest["database"]["schema_version"] = ["v" * (8 * 1024**2)]
        with pytest.raises(RuntimeError, match="manifest"):
            backup_cli.capture_archive(info, staging)
        assert not (staging / "recovery.tar").exists()
        return
    archive = backup_cli.capture_archive(info, staging)
    decoded = tmp_path / "decoded"
    result = backup_cli.validate_archive(archive, decoded)
    assert result["credentials"] == {"firebase_credentials": "credentials/firebase.json"}
    assert (decoded / "credentials/firebase.json").read_bytes() == credential.read_bytes()
    assert (decoded / "config/production.env").read_text() == "SIGNED_URL_SECRET=fixture-only\n"
    assert (decoded / "database.dump").read_bytes() == b"PGDMP fixture dump"
    assert (decoded / "media/nested/binary.bin").read_bytes() == b"\x00\xfforiginal"
    assert (decoded / "media/empty").is_dir()


@pytest.fixture
def restore_fixture(backup_cli, installation, tmp_path, age_keys, monkeypatch):
    root, info, events, stopped = installation
    identity, recipient = age_keys
    (root / "current.json").write_text(json.dumps(info["state"]))
    archive = tmp_path / "restore.age"
    _real_age_file(backup_cli, tmp_path / "payload.tar", archive,
                   ["--encrypt", "--recipient", recipient])
    monkeypatch.setattr(backup_cli, "age_file", lambda source, output, args:
                        _real_age_file(backup_cli, source, output, args))
    monkeypatch.setattr(backup_cli, "prepare_restore", lambda *args: dict(info), raising=False)

    def replace(*args):
        assert stopped == {"api", "w1", "w2"}
        events.append(["replace-data"])

    monkeypatch.setattr(backup_cli, "restore_data", replace, raising=False)
    monkeypatch.setattr(backup_cli, "verify_restored", lambda *args: None, raising=False)
    return root, archive, identity, recipient, events, stopped


def test_restore_validation_before_mutation(backup_cli, restore_fixture, tmp_path):
    root, archive, identity, recipient, events, _ = restore_fixture
    archive.write_bytes(archive.read_bytes()[:-20])
    before = (root / "current.json").read_bytes()
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        backup_cli.restore(root, archive, identity, confirm_replace=True,
                           safety_recipient=recipient, safety_output=tmp_path / "safety.age")
    assert not events
    assert (root / "current.json").read_bytes() == before


@pytest.mark.parametrize("confirmed,safety", [(False, True), (True, False)])
def test_restore_requires_confirmation_and_safety_archive(backup_cli, restore_fixture,
                                                         tmp_path, confirmed, safety):
    root, archive, identity, recipient, events, _ = restore_fixture
    with pytest.raises(ValueError):
        backup_cli.restore(root, archive, identity, confirm_replace=confirmed,
                           safety_recipient=recipient if safety else None,
                           safety_output=tmp_path / "safety.age" if safety else None)
    assert not any("stop" in event for event in events)


def test_safety_failure_recovers_original_services(backup_cli, restore_fixture,
                                                   tmp_path, monkeypatch):
    root, archive, identity, recipient, events, stopped = restore_fixture
    monkeypatch.setattr(backup_cli, "capture_archive", lambda *_:
                        (_ for _ in ()).throw(RuntimeError("safety capture failed")))
    with pytest.raises(RuntimeError, match="safety"):
        backup_cli.restore(root, archive, identity, confirm_replace=True,
                           safety_recipient=recipient, safety_output=tmp_path / "safety.age")
    assert not stopped
    assert ["replace-data"] not in events


@pytest.mark.parametrize("failure", ["signal", "health", "replace"])
def test_restore_interrupt_and_health_failure_leave_writers_stopped(backup_cli, restore_fixture,
                                                                   tmp_path, monkeypatch, failure):
    root, archive, identity, recipient, events, stopped = restore_fixture
    if failure == "health":
        monkeypatch.setattr(backup_cli.deploy, "verify_public_health", lambda *_:
                            (_ for _ in ()).throw(RuntimeError("health failed")))
    else:
        def broken(*_):
            if failure == "signal":
                signal.raise_signal(signal.SIGTERM)
            raise RuntimeError("replacement failed")
        monkeypatch.setattr(backup_cli, "restore_data", broken)
    with pytest.raises(RuntimeError, match="stopped"):
        backup_cli.restore(root, archive, identity, confirm_replace=True,
                           safety_recipient=recipient, safety_output=tmp_path / "safety.age")
    assert stopped == {"api", "w1", "w2"}
    assert (tmp_path / "safety.age").exists()
    assert events[-1][-3:] != ["up", "backend", "worker"]


def test_restore_commits_configuration_after_safety_capture(backup_cli, restore_fixture, tmp_path):
    root, archive, identity, recipient, events, stopped = restore_fixture
    backup_cli.restore(root, archive, identity, confirm_replace=True,
                       safety_recipient=recipient, safety_output=tmp_path / "safety.age")
    assert events.index(["capture"]) < events.index(["replace-data"])
    assert (root / "config/production.env").read_text() == "SIGNED_URL_SECRET=fixture-only\n"
    assert not stopped


def test_fresh_target_rejects_existing_resources(backup_cli, tmp_path, monkeypatch):
    monkeypatch.setattr(backup_cli.deploy, "run", lambda *_, **__: b"fixture-existing-container\n")
    with pytest.raises(ValueError):
        backup_cli.ensure_fresh_project()


def test_restore_relocates_firebase_credentials(backup_cli, tmp_path):
    root, _, _ = payload(tmp_path, backup_cli)
    (root / "config/production.env").write_text(
        "SIGNED_URL_SECRET=keep-exact\nFCM_CREDENTIALS_FILE=/old/external.json\n")
    target = PurePosixPath("/srv/new-root")
    text = backup_cli.relocated_environment(root, target, True)
    assert 'FCM_CREDENTIALS_FILE="' + str(target / "config/firebase.json") + '"' in text
    assert "SIGNED_URL_SECRET=keep-exact\n" in text
    assert "/old/external.json" not in text


def test_cli_help_and_error_redaction(backup_cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backup_cli.sys, "argv", ["backup.py", "--help"])
    with pytest.raises(SystemExit) as result:
        backup_cli.main()
    assert result.value.code == 0
    assert "restore" in capsys.readouterr().out
    monkeypatch.setattr(backup_cli.sys, "platform", "linux")
    monkeypatch.setattr(backup_cli.sys, "argv", ["backup.py", "backup", "--root", str(tmp_path),
                                               "--recipient", "bad", "--output", "out.age"])
    monkeypatch.setattr(backup_cli, "backup", lambda *args:
                        (_ for _ in ()).throw(ValueError("secret-fixture-do-not-log")))
    assert backup_cli.main() == 1
    assert "secret-fixture-do-not-log" not in capsys.readouterr().err


def test_cli_loads_all_helpers_before_execution(tmp_path):
    import sys

    if sys.platform != "linux":
        pytest.skip("actual recovery entry point requires Linux")
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "backup.py"),
                             "backup", "--root", str(tmp_path), "--recipient", "bad",
                             "--output", str(tmp_path / "backup.age")],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "NameError" not in result.stderr
    assert "ValueError" in result.stderr


def test_fresh_target_rejects_resolved_custom_volume(backup_cli, tmp_path, monkeypatch):
    root, _, manifest = payload(tmp_path, backup_cli)
    config = storage_config()
    config["volumes"]["media-data"]["name"] = "shared-media"
    config["services"]["db"].update({"image": "postgres:18", "environment": {
        "POSTGRES_DB": "dojo", "POSTGRES_USER": "dojo", "POSTGRES_PASSWORD": "fixture"}})

    def external(args, **kwargs):
        if "config" in args:
            return json.dumps(config).encode()
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": manifest["database"]["image"]}]).encode()
        if args[:3] == ["docker", "volume", "ls"]:
            return b"shared-media\n"
        if args[:2] == ["docker", "ps"]:
            return b""
        pytest.fail("existing resolved volume must fail before dump preflight or mutation")

    monkeypatch.setattr(backup_cli.deploy, "run", external)
    with pytest.raises(ValueError, match="existing"):
        backup_cli.prepare_restore(tmp_path / "fresh", root, manifest, None)
    assert not (tmp_path / "fresh").exists()


def storage_config():
    names = ("db-data", "media-data", "worker-health", "caddy-data")
    mounts = {
        "db": [("db-data", "/var/lib/postgresql")],
        "backend": [("media-data", "/media"), ("worker-health", "/run/dojo-worker")],
        "worker": [("media-data", "/media"), ("worker-health", "/run/dojo-worker")],
        "gateway": [("caddy-data", "/data")],
    }
    return {"volumes": {name: {"name": f"fixture_{name}"} for name in names},
            "services": {service: {"volumes": [
                {"type": "volume", "source": name, "target": target}
                for name, target in volumes]} for service, volumes in mounts.items()}}


@pytest.mark.parametrize("mutation", ["external", "bind-driver", "bind-mount", "alias"])
def test_unsupported_storage_rejected_before_mutation(backup_cli, mutation):
    config = storage_config()
    media = config["volumes"]["media-data"]
    if mutation == "external":
        media["external"] = True
    elif mutation == "bind-driver":
        media["driver_opts"] = {"type": "none", "o": "bind", "device": "/unrelated"}
    elif mutation == "bind-mount":
        config["services"]["backend"]["volumes"][0]["type"] = "bind"
    else:
        media["name"] = config["volumes"]["db-data"]["name"]
    with pytest.raises(ValueError):
        backup_cli.validate_storage(config)


def test_fresh_restore_refuses_shell_override(backup_cli, tmp_path, monkeypatch):
    root, _, manifest = payload(tmp_path, backup_cli)
    monkeypatch.setenv("SIGNED_URL_SECRET", "do-not-restore-this-shell-value")

    def no_docker(*args, **kwargs):
        pytest.fail("overridden archive settings must fail before prospective Docker rendering")

    monkeypatch.setattr(backup_cli.deploy, "run", no_docker)
    with pytest.raises(ValueError, match="interpolation"):
        backup_cli.prepare_restore(tmp_path / "fresh-target", root, manifest, None)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM,
                                     getattr(signal, "SIGHUP", None)])
def test_backup_restart_interrupt_recovers_all_replicas(backup_cli, installation,
                                                        tmp_path, age_keys, monkeypatch, signum):
    if signum is None:
        pytest.skip("SIGHUP requires Linux")
    root, _, _, stopped = installation
    monkeypatch.setattr(backup_cli, "age_file", lambda source, output, args:
                        _real_age_file(backup_cli, source, output, args))
    external = backup_cli.deploy.run
    attempts = []

    def interrupted_start(args, **kwargs):
        if "up" in args:
            attempts.append(args)
            if len(attempts) == 1:
                stopped.discard("api")  # Compose already started one replica.
                signal.raise_signal(signum)
        return external(args, **kwargs)

    monkeypatch.setattr(backup_cli.deploy, "run", interrupted_start)
    with pytest.raises(RuntimeError):
        backup_cli.backup(root, age_keys[1], tmp_path / "backup.age")
    assert len(attempts) == 2, "restart interruption must retry original application recovery"
    assert not stopped
    assert (tmp_path / "backup.age").is_file()


@pytest.mark.parametrize("operation", ["backup", "restore", "shared-empty-restore"])
def test_invalid_root_does_not_change_unrelated_directory(backup_cli, tmp_path, operation):
    import sys

    if sys.platform != "linux":
        pytest.skip("production root permissions require Linux")
    root = tmp_path / "unrelated"
    root.mkdir()
    root.chmod(0o1777 if operation == "shared-empty-restore" else 0o755)
    if operation != "shared-empty-restore":
        (root / "keep.txt").write_bytes(b"unrelated data")
    mode = root.stat().st_mode
    with pytest.raises(ValueError):
        if operation == "backup":
            backup_cli.backup(root, "bad", tmp_path / "output.age")
        else:
            backup_cli.restore(root, tmp_path / "archive.age", tmp_path / "key.txt",
                               confirm_replace=True)
    assert root.stat().st_mode == mode
    expected = [] if operation == "shared-empty-restore" else ["keep.txt"]
    assert sorted(p.name for p in root.iterdir()) == expected


@pytest.mark.parametrize("monitoring", [False, True])
@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", ["", "\ufeff"])
def test_restore_preserves_environment_bytes(backup_cli, tmp_path, monitoring, line_ending, bom):
    root, _, _ = payload(tmp_path, backup_cli)
    target = PurePosixPath("/srv/new-root")
    prefix = bom + "export FCM_CREDENTIALS_FILE = "
    suffix = line_ending + "SIGNED_URL_SECRET=keep-exact" + line_ending
    original = prefix + "'/old/external.json'" + suffix
    (root / "config/production.env").write_bytes(original.encode("utf-8"))
    expected = (prefix + '"/srv/new-root/config/firebase.json"' + suffix
                if monitoring else original)
    result = backup_cli.relocated_environment(root, target, monitoring)
    assert result.encode("utf-8") == expected.encode("utf-8")
