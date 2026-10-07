"""Disposable real Compose/PG rollback. Never uses ops/.env or dojo-prod resources."""

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import test_deploy
from test_deploy import NEW, OLD

deployment_cli = test_deploy.cli


@pytest.fixture(scope="module")
def image_ids():
    required = os.environ.get("REQUIRE_DEPLOY_INTEGRATION") == "1"
    if sys.platform != "linux":
        if required:
            pytest.fail("required deployment integration needs Linux")
        pytest.skip("Linux Docker integration; set REQUIRE_DEPLOY_INTEGRATION=1 in CI")
    tag = os.environ.get("VERIFY_IMAGE_TAG", "issue39")
    ids = {}
    for service in ("backend", "worker", "gateway"):
        result = subprocess.run(
            ["docker", "image", "inspect", f"dojo-{service}-verify:{tag}", "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            if required:
                pytest.fail(f"missing required verification image: {service}")
            pytest.skip(f"build dojo-{service}-verify:{tag} first")
        ids[service] = result.stdout.strip()
    candidate_tag = f"dojo-backend-verify:{tag}-candidate"
    subprocess.run(
        ["docker", "build", "-t", candidate_tag, "-f", "-", "."],
        input=f"FROM dojo-backend-verify:{tag}\nLABEL issue39.candidate=yes\n".encode(),
        capture_output=True,
        check=True,
    )
    ids["candidate"] = (
        subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                candidate_tag,
                "--format",
                "{{.Id}}",
            ]
        )
        .decode()
        .strip()
    )
    assert ids["candidate"] != ids["backend"]
    return ids


@pytest.mark.parametrize("failure", ["health", "preflight", "interruption", "none"])
def test_real_snapshot_rehearsal_and_rollback(
    deployment_cli,
    image_ids,
    tmp_path,
    monkeypatch,
    failure,
):
    cli = deployment_cli
    project = "verifydeploy" + uuid.uuid4().hex[:10]
    monkeypatch.setattr(cli, "PROJECT", project)
    monkeypatch.setattr(cli, "verify_public_health", lambda *args: None)
    root = tmp_path / "install"
    (root / "config").mkdir(parents=True)
    root.chmod(0o700)
    (root / "config/production.env").write_text(
        "POSTGRES_PASSWORD=integration-only\nPOSTGRES_USER=dojo\nPOSTGRES_DB=dojo\n"
        "SIGNED_URL_SECRET=integration-only\nPUBLIC_BASE_URL=https://fixture.invalid\n"
        "PUBLIC_HTTPS_ORIGIN=https://fixture.invalid\nGATEWAY_HTTP_PORT=0\n"
        "ANDROID_CURRENT_VERSION_CODE=4\n",
        encoding="utf-8",
    )
    old_images = {
        s: f"ghcr.io/fixture/{s}@sha256:{'a' * 64}" for s in ("backend", "worker", "gateway")
    }
    new_images = {
        s: f"ghcr.io/fixture/{s}@sha256:{'b' * 64}" for s in ("backend", "worker", "gateway")
    }
    references = {old_images[s]: image_ids[s] for s in old_images}
    references.update(
        {new_images[s]: image_ids["candidate" if s == "backend" else s] for s in new_images}
    )
    old = cli.build_bundle(OLD, old_images, tmp_path / "old")
    new = cli.build_bundle(NEW, new_images, tmp_path / "new")
    subprocess_run = subprocess.run

    def diagnostic_run(args, **kwargs):
        result = subprocess_run(args, **kwargs)
        if result.returncode and "pg_restore" in args:
            print("Fixture restore failed:", result.stderr.decode(errors="replace"))
        return result

    monkeypatch.setattr(cli.subprocess, "run", diagnostic_run)
    original = cli.run
    commands = []
    restored = []
    rehearsal = []
    interrupted_initializers = []

    def mapped(args, **kwargs):
        args = [str(a) for a in args]
        commands.append(args.copy())
        if args[:2] == ["docker", "compose"] and "-f" in args:
            manifest = Path(args[args.index("-f") + 1]).parent / "release.json"
            info = json.loads(manifest.read_text())
            override = tmp_path / (info["sha"] + "-mapped.json")
            services = {
                name: {"image": references[image]} for name, image in info["images"].items()
            }
            services["init"] = {"image": references[info["images"]["backend"]]}
            if info["sha"] == NEW and failure == "health":
                services["backend"]["healthcheck"] = {
                    "test": ["CMD", ".venv/bin/python", "-c", "raise SystemExit(1)"],
                    "interval": "1s",
                    "timeout": "1s",
                    "retries": 1,
                    "start_period": "0s",
                }
            override.write_text(json.dumps({"services": services}))
            images_index = next(i for i, a in enumerate(args) if a.endswith("images.json"))
            args[images_index] = str(override)
            if "pull" in args and "up" not in args:
                # External registry traffic is the only image boundary substituted.
                for image in info["images"].values():
                    original(["docker", "image", "inspect", references[image]])
                return b""
            if failure == "interruption" and "run" in args and "init" in args:
                name = (
                    args[args.index("--name") + 1]
                    if "--name" in args
                    else project + "-test-interrupted-init"
                )
                interrupted_initializers.append(name)
                if "--name" not in args:
                    args[args.index("init") : args.index("init")] = ["--name", name]
                args.insert(args.index("init"), "-d")
                script = (
                    "import os, psycopg; from pathlib import Path; "
                    "conn=psycopg.connect(os.environ['DATABASE_URL'].replace("
                    "'postgresql+psycopg://','postgresql://'), "
                    f"application_name={name!r}); "
                    "conn.execute('CREATE TABLE interrupted_migration(value text)'); "
                    "Path('/tmp/migration-active').write_text('active'); "
                    "conn.execute('SELECT pg_sleep(600)')"
                )
                original(args + [".venv/bin/python", "-c", script], **kwargs)
                deadline = time.monotonic() + 15
                while True:
                    try:
                        original(
                            [
                                "docker",
                                "exec",
                                name,
                                ".venv/bin/python",
                                "-c",
                                "from pathlib import Path; "
                                "assert Path('/tmp/migration-active').exists()",
                            ]
                        )
                        break
                    except RuntimeError:
                        assert time.monotonic() < deadline, "initializer did not open transaction"
                        time.sleep(0.2)
                signal.raise_signal(signal.SIGTERM)
                pytest.fail("deployment signal was not handled")
            result = original(args, **kwargs)
            if args[-3:] == ["config", "--format", "json"]:
                config = json.loads(result)
                for s in (*info["images"], "init"):
                    config["services"][s]["image"] = info["images"]["backend" if s == "init" else s]
                return json.dumps(config).encode()
            return result
        args = [references.get(a, a) for a in args]
        if "dojo.schema" in args:
            rehearsal.append(args)
            if failure == "preflight":
                # Execute a real failed migration process against the clone only.
                args[-3:] = [".venv/bin/python", "-c", "raise SystemExit(7)"]
        result = original(args, **kwargs)
        if "pg_restore" in args:
            value = (
                original(
                    [
                        "docker",
                        "exec",
                        args[3],
                        "psql",
                        "-U",
                        "dojo",
                        "-d",
                        "dojo",
                        "-tAc",
                        "SELECT value FROM deployment_sentinel",
                    ]
                )
                .decode()
                .strip()
            )
            restored.append(value)
        return result

    monkeypatch.setattr(cli, "run", mapped)
    command = cli.compose(old, root, "existing-proxy", False)
    try:
        cli.run(
            command
            + ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180"]
        )
        cli.adopt_baseline(
            old, root, mode="existing-proxy", monitoring=False, origin="https://fixture.invalid"
        )
        ids = cli.running(command, old_images)
        db, backend = ids["db"][0], ids["backend"][0]
        original(
            [
                "docker",
                "exec",
                db,
                "psql",
                "-U",
                "dojo",
                "-d",
                "dojo",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "CREATE TABLE deployment_sentinel(value text);",
                "-c",
                "INSERT INTO deployment_sentinel VALUES ('keep-database');",
            ]
        )
        original(
            [
                "docker",
                "exec",
                backend,
                ".venv/bin/python",
                "-c",
                "from pathlib import Path; "
                "Path('/media/deployment-sentinel').write_text('keep-media')",
            ]
        )
        version_before = original(
            [
                "docker",
                "exec",
                db,
                "psql",
                "-U",
                "dojo",
                "-d",
                "dojo",
                "-tAc",
                "SELECT version_num FROM alembic_version",
            ]
        )
        commands.clear()
        if failure == "none":
            cli.deploy(
                new,
                root,
                mode="existing-proxy",
                monitoring=False,
                origin="https://fixture.invalid",
                health_timeout=90,
            )
        else:
            with pytest.raises(RuntimeError):
                cli.deploy(
                    new,
                    root,
                    mode="existing-proxy",
                    monitoring=False,
                    origin="https://fixture.invalid",
                    health_timeout=90,
                )
        expected = NEW if failure == "none" else OLD
        assert json.loads((root / "current.json").read_text())["sha"] == expected
        assert restored == ["keep-database"]
        assert len(rehearsal) == 1
        assert len(list((root / "snapshots").glob("*.dump"))) == 1
        bundle = root / "releases" / expected
        running = cli.running(
            cli.compose(bundle, root, "existing-proxy", False),
            new_images if failure == "none" else old_images,
        )
        current_backend = running["backend"][0]
        expected_id = image_ids["candidate" if failure == "none" else "backend"]
        assert cli.inspect_container(current_backend)["Image"] == expected_id
        assert (
            original(
                [
                    "docker",
                    "exec",
                    db,
                    "psql",
                    "-U",
                    "dojo",
                    "-d",
                    "dojo",
                    "-tAc",
                    "SELECT value FROM deployment_sentinel",
                ]
            ).strip()
            == b"keep-database"
        )
        assert (
            original(
                [
                    "docker",
                    "exec",
                    current_backend,
                    ".venv/bin/python",
                    "-c",
                    "from pathlib import Path; "
                    "print(Path('/media/deployment-sentinel').read_text())",
                ]
            ).strip()
            == b"keep-media"
        )
        assert (
            original(
                [
                    "docker",
                    "exec",
                    db,
                    "psql",
                    "-U",
                    "dojo",
                    "-d",
                    "dojo",
                    "-tAc",
                    "SELECT version_num FROM alembic_version",
                ]
            )
            == version_before
        )
        assert not any("down" in c or "downgrade" in c for c in commands)
        if failure == "preflight":
            assert not any("init" in c and "run" in c for c in commands)
        if failure == "interruption":
            name = interrupted_initializers[0]
            assert not original(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"]).strip()
            assert (
                original(
                    [
                        "docker",
                        "exec",
                        db,
                        "psql",
                        "-U",
                        "dojo",
                        "-d",
                        "dojo",
                        "-tAc",
                        f"SELECT count(*) FROM pg_stat_activity WHERE application_name='{name}'",
                    ]
                ).strip()
                == b"0"
            )
            assert (
                original(
                    [
                        "docker",
                        "exec",
                        db,
                        "psql",
                        "-U",
                        "dojo",
                        "-d",
                        "dojo",
                        "-tAc",
                        "SELECT to_regclass('interrupted_migration') IS NULL",
                    ]
                ).strip()
                == b"t"
            )
        # Independently restore the retained file after recovery, not a live DB
        # re-dump. Preflight's temporary DB and old backend prove readability.
        failure = "none"
        cli.preflight(
            next((root / "snapshots").glob("*.dump")),
            old_images,
            old_images,
            cli.inspect_container(db)["Image"],
            90,
        )
        assert restored == ["keep-database", "keep-database"]
    finally:
        # Only this explicit test project is permitted to delete its fixtures.
        assert project.startswith("verifydeploy") and project != "dojo-prod"
        for name in interrupted_initializers:
            try:
                original(["docker", "rm", "-f", name])
            except RuntimeError:
                assert not original(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"]).strip()
        cli.run(command + ["down", "-v", "--remove-orphans"])


@pytest.mark.parametrize("mode", ["dedicated", "existing-proxy"])
@pytest.mark.parametrize("monitoring", [False, True])
def test_bundle_renders_proxy_and_monitoring_modes(deployment_cli, tmp_path, mode, monitoring):
    cli = deployment_cli
    root = tmp_path / "installation"
    (root / "config").mkdir(parents=True)
    credentials = tmp_path / "synthetic.json"
    credentials.write_text('{"project_id":"fixture-only"}')
    (root / "config/production.env").write_text(
        "POSTGRES_PASSWORD=fixture-only\nSIGNED_URL_SECRET=fixture-only\nDOMAIN=fixture.invalid\n"
        "PUBLIC_BASE_URL=https://fixture.invalid\nPUBLIC_HTTPS_ORIGIN=https://fixture.invalid\n"
        f"FCM_CREDENTIALS_FILE={credentials.as_posix()}\nFCM_PROJECT_ID=fixture-only\n",
    )
    images = {s: f"ghcr.io/fixture/{s}@sha256:{'a' * 64}" for s in ("backend", "worker", "gateway")}
    bundle = cli.build_bundle(OLD, images, tmp_path / "bundle")
    rendered = json.loads(
        cli.run(cli.compose(bundle, root, mode, monitoring) + ["config", "--format", "json"])
    )
    assert rendered["services"]["backend"]["image"] == images["backend"]
    enabled = rendered["services"]["worker"]["environment"].get("FCM_ENABLED")
    assert (str(enabled).lower() == "true") is monitoring
