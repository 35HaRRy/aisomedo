"""Real recovery on random disposable projects. No production files or credentials."""

import json
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from test_backup import age_keys as age_keys
from test_backup import backup_cli as backup_cli


@pytest.fixture
def recovery_installation(backup_cli, tmp_path, monkeypatch, request):
    required = os.environ.get("REQUIRE_BACKUP_INTEGRATION") == "1"
    if sys.platform != "linux" or not shutil.which("age"):
        if required:
            pytest.fail("required recovery integration needs Linux and age")
        pytest.skip("Linux/age integration; set REQUIRE_BACKUP_INTEGRATION=1 in CI")
    cli = backup_cli
    original = cli.deploy.run
    tag = os.environ.get("VERIFY_IMAGE_TAG", "issue23")
    try:
        original(["docker", "info"], step="test Docker availability")
        references = {}
        images = {}
        for service in ("backend", "worker", "gateway"):
            image = f"dojo-{service}-verify:{tag}"
            image_id = json.loads(original(["docker", "image", "inspect", image]))[0]["Id"]
            images[service] = f"ghcr.io/fixture/{service}@sha256:{'a' * 64}"
            references[images[service]] = image_id
    except (RuntimeError, FileNotFoundError):
        if required:
            pytest.fail("required recovery verification images or Docker are unavailable")
        pytest.skip("build verification images and start Docker first")
    project = "verifybackup" + uuid.uuid4().hex[:12]
    monkeypatch.setattr(cli.deploy, "PROJECT", project)
    monitoring = bool(getattr(request, "param", False))
    root = tmp_path / "install"
    (root / "config").mkdir(parents=True)
    credential = tmp_path / "external-firebase.json"
    if monitoring:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        credential.write_text(json.dumps({
            "type": "service_account", "project_id": "fixture-not-a-project",
            "private_key_id": "fixture-only", "private_key": key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()).decode(),
            "client_email": "fixture@fixture-not-a-project.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token"}))
    (root / "config/production.env").write_text(
        "POSTGRES_PASSWORD=integration-only\nPOSTGRES_USER=dojo\nPOSTGRES_DB=dojo\n"
        "SIGNED_URL_SECRET=original-setting\nPUBLIC_BASE_URL=https://fixture.invalid\n"
        "PUBLIC_HTTPS_ORIGIN=https://fixture.invalid\nGATEWAY_HTTP_PORT=0\n"
        f"FCM_CREDENTIALS_FILE={credential}\nFCM_PROJECT_ID=fixture-not-a-project\n"
        "MONITORING_INTERVAL_SECONDS=3600\nMONITORING_DISK_LOW_PERCENT=0.1\n"
        "MONITORING_DISK_RECOVERY_PERCENT=1\n")
    if monitoring:
        environment = root / "config/production.env"
        environment.write_bytes(environment.read_bytes().replace(b"\n", b"\r\n"))
    release = cli.deploy.build_bundle("1" * 40, images, tmp_path / "release")

    def mapped(args, **kwargs):
        args = [str(a) for a in args]
        if args[:2] == ["docker", "compose"]:
            bundle = Path(args[args.index("-f") + 1]).parent
            override = tmp_path / "local-images.json"
            services = {name: {"image": references[image]} for name, image in images.items()}
            services["init"] = {"image": references[images["backend"]]}
            override.write_text(json.dumps({"services": services}))
            index = next(i for i, a in enumerate(args) if a.endswith("images.json"))
            args[index] = str(override)
            result = original(args, **kwargs)
            if args[-3:] == ["config", "--format", "json"]:
                config = json.loads(result)
                for name in (*images, "init"):
                    config["services"][name]["image"] = images[
                        "backend" if name == "init" else name]
                return json.dumps(config).encode()
            assert (bundle / "release.json").is_file()
            return result
        return original([references.get(a, a) for a in args], **kwargs)

    monkeypatch.setattr(cli.deploy, "run", mapped)

    def public_health(*_):
        gateway = original(["docker", "ps", "-q", "--filter",
                            f"label=com.docker.compose.project={project}", "--filter",
                            "label=com.docker.compose.service=gateway"]).decode().strip()
        original(["docker", "exec", gateway, "curl", "-fsS", "http://127.0.0.1/ready"])
        original(["docker", "exec", gateway, "curl", "-fsS",
                  "http://127.0.0.1/web-health.txt"])

    monkeypatch.setattr(cli.deploy, "verify_public_health", public_health)
    command = cli.deploy.compose(release, root, "existing-proxy", monitoring)
    try:
        mapped(command + ["up", "-d", "--no-build", "--pull", "never", "--scale", "worker=2",
                          "--wait", "--wait-timeout", "180"], timeout=240)
        cli.deploy.adopt_baseline(release, root, mode="existing-proxy", monitoring=monitoring,
                                  origin="https://fixture.invalid")
        info = cli.read_installation(root)
        cli.query(info, "CREATE TABLE recovery_sentinel(value text); "
                        "INSERT INTO recovery_sentinel VALUES ('original-database');")
        backend = info["containers"]["backend"][0]
        original(["docker", "exec", backend, ".venv/bin/python", "-c",
                  "from pathlib import Path; p=Path('/media'); "
                  "(p/'branding/nested').mkdir(parents=True, exist_ok=True); "
                  "(p/'branding/empty').mkdir(exist_ok=True); "
                  "(p/'branding/nested/binary').write_bytes(b'\\x00\\xfforiginal')"])
        yield cli, root, project, images, credential, original
    finally:
        # Exact randomly named project owned by this fixture; never dojo-prod.
        mapped(command + ["down", "--volumes", "--remove-orphans"], timeout=300)


@pytest.mark.parametrize("recovery_installation", [False, True], indirect=True)
def test_existing_installation_roundtrip(recovery_installation, tmp_path, age_keys):
    cli, root, _, _, credential, original = recovery_installation
    identity, recipient = age_keys
    original_env = (root / "config/production.env").read_bytes().decode("utf-8")
    original_secret = credential.read_bytes() if credential.exists() else None
    archive = tmp_path / "backup.age"
    cli.backup(root, recipient, archive)
    assert b"original-database" not in archive.read_bytes()
    info = cli.read_installation(root)
    cli.query(info, "UPDATE recovery_sentinel SET value='changed-database'")
    (root / "config/production.env").write_bytes(original_env.replace(
        "original-setting", "changed-setting").encode("utf-8"))
    original(["docker", "exec", info["containers"]["backend"][0], ".venv/bin/python", "-c",
              "from pathlib import Path; p=Path('/media'); "
              "(p/'branding/nested/binary').write_bytes(b'changed'); "
              "(p/'extra').write_bytes(b'remove')"])
    cli.restore(root, archive, identity, confirm_replace=True, safety_recipient=recipient,
                safety_output=tmp_path / "safety.age")
    restored = cli.read_installation(root)
    value = cli.query(restored, "SELECT value FROM recovery_sentinel").strip()
    assert value == b"original-database"
    expected_env = original_env
    if original_secret:
        expected_env = expected_env.replace(f"FCM_CREDENTIALS_FILE={credential}",
            "FCM_CREDENTIALS_FILE=" + json.dumps(str(root / "config/firebase.json")))
        assert (root / "config/firebase.json").read_bytes() == original_secret
    assert (root / "config/production.env").read_bytes() == expected_env.encode("utf-8")
    assert restored["worker_count"] == 2
    inventory = json.loads(cli.volume_helper(restored, cli.MEDIA_INVENTORY))
    assert "media/extra" not in inventory
    assert inventory["media/branding/empty"] == {"type": "directory"}
    binary = original(["docker", "exec", restored["containers"]["backend"][0],
                       ".venv/bin/python", "-c", "import sys; from pathlib import Path; "
                       "sys.stdout.buffer.write(Path('/media/branding/nested/binary').read_bytes())"])
    assert binary == b"\x00\xfforiginal"


def test_fresh_root_roundtrip(recovery_installation, tmp_path, age_keys):
    cli, root, _, _, _, _ = recovery_installation
    identity, recipient = age_keys
    archive = tmp_path / "backup.age"
    cli.backup(root, recipient, archive)
    info = cli.read_installation(root)
    cli.deploy.run(info["command"] + ["down", "--volumes", "--remove-orphans"])
    target = tmp_path / "new-installation"
    target.mkdir()
    cli.restore(target, archive, identity, confirm_replace=True)
    restored = cli.read_installation(target)
    value = cli.query(restored, "SELECT value FROM recovery_sentinel").strip()
    assert value == b"original-database"
    assert restored["state"]["sha"] == "1" * 40
    environment = (target / "config/production.env").read_bytes()
    assert environment == (root / "config/production.env").read_bytes()


def test_restore_failure_keeps_writers_stopped(recovery_installation, tmp_path, age_keys,
                                              monkeypatch):
    cli, root, _, _, _, original = recovery_installation
    identity, recipient = age_keys
    archive = tmp_path / "backup.age"
    cli.backup(root, recipient, archive)
    restore_data = cli.restore_data

    def fail_after_replacement(*args):
        restore_data(*args)
        raise RuntimeError("fixture failure after real replacement")

    monkeypatch.setattr(cli, "restore_data", fail_after_replacement)
    with pytest.raises(RuntimeError, match="stopped"):
        cli.restore(root, archive, identity, confirm_replace=True,
                    safety_recipient=recipient, safety_output=tmp_path / "safety.age")
    command = cli.deploy.compose(root / "releases" / ("1" * 40), root, "existing-proxy", False)
    for service in ("backend", "worker"):
        ids = cli.deploy.run(command + ["ps", "--all", "-q", service]).decode().split()
        assert ids
        assert all(not json.loads(original(["docker", "inspect", i]))[0]["State"]["Running"]
                   for i in ids)
    assert (tmp_path / "safety.age").is_file()
