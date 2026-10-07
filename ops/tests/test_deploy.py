"""Release trust boundaries and orchestration with only external Docker calls doubled."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "deploy.py"
OLD = "1" * 40
NEW = "2" * 40
IMAGES = {
    name: f"ghcr.io/example/{name}@sha256:{'a' * 64}" for name in ("backend", "worker", "gateway")
}


@pytest.fixture
def cli():
    assert SCRIPT.exists(), "deployment transaction CLI is missing"
    spec = importlib.util.spec_from_file_location("deploy_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_roundtrip_and_pins_init(cli, tmp_path):
    bundle = cli.build_bundle(NEW, IMAGES, tmp_path / "bundle")
    assert cli.validate_bundle(bundle) == IMAGES
    override = json.loads((bundle / "images.json").read_text())
    assert override["services"]["init"]["image"] == IMAGES["backend"]
    assert not any(".env" in p.name for p in bundle.iterdir())


@pytest.mark.parametrize(
    "sha,images",
    [
        ("../escape", IMAGES),
        (NEW, {**IMAGES, "backend": "latest"}),
        (NEW, {**IMAGES, "evil": IMAGES["backend"]}),
    ],
)
def test_invalid_metadata_rejected_before_output(cli, tmp_path, sha, images):
    with pytest.raises(ValueError):
        cli.build_bundle(sha, images, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("mutation", ["override", "missing", "metadata", "symlink"])
def test_tampered_bundle_rejected(cli, tmp_path, mutation):
    bundle = cli.build_bundle(NEW, IMAGES, tmp_path / "bundle")
    if mutation == "override":
        (bundle / "images.json").write_text('{"services":{"evil":{"image":"alpine"}}}')
    elif mutation == "missing":
        (bundle / "docker-compose.prod.yml").unlink()
    elif mutation == "metadata":
        (bundle / "release.json").write_text(json.dumps({"sha": "../escape", "images": IMAGES}))
    else:
        (bundle / "images.json").unlink()
        try:
            (bundle / "images.json").symlink_to(tmp_path / "outside.json")
        except OSError:
            pytest.skip("symlinks require Windows developer mode")
    with pytest.raises((ValueError, FileNotFoundError)):
        cli.validate_bundle(bundle)


class DockerDouble:
    def __init__(self, fail=None, unhealthy=False):
        self.calls = []
        self.fail = fail
        self.failed = False
        self.unhealthy = unhealthy
        self.stopped = False

    def __call__(self, args, *, input=None, stdout=None, timeout=300):
        self.calls.append(list(map(str, args)))
        command = " ".join(map(str, args))
        if self.fail and self.fail in command and not self.failed:
            self.failed = True
            raise RuntimeError("synthetic Docker failure")
        if " stop " in command:
            self.stopped = True
        if " up " in command:
            self.stopped = False
        if "config --format json" in command:
            return json.dumps(
                {
                    "services": {
                        "db": {
                            "image": "postgres:16-alpine",
                            "environment": {
                                "POSTGRES_USER": "dojo",
                                "POSTGRES_DB": "dojo",
                                "POSTGRES_PASSWORD": "fixture",
                            },
                        },
                        "backend": {"environment": {"SIGNED_URL_SECRET": "fixture"}},
                    }
                }
            ).encode()
        if args == ["docker", "compose", "up", "--help"]:
            return b"--wait --wait-timeout --no-deps --pull"
        if args[:2] == ["docker", "ps"]:
            return b""
        if " ps " in command:
            return (str(args[-1]) + "-id\n").encode()
        if args[:3] == ["docker", "image", "inspect"]:
            return b"sha256:fixture\n"
        if args[:2] == ["docker", "inspect"]:
            return json.dumps(
                [
                    {
                        "State": {
                            "Running": not self.stopped or "db" in args[-1],
                            "Health": {"Status": "unhealthy" if self.unhealthy else "healthy"},
                        },
                        "Image": "sha256:fixture",
                    }
                ]
            ).encode()
        if "pg_database_size" in command:
            return b"1024\n"
        if "pg_stat_activity" in command:
            return b"0\n"
        if "pg_dump" in command:
            stdout.write(b"PGDMPsynthetic-snapshot")
        return b""


@pytest.fixture
def installation(cli, tmp_path, monkeypatch):
    root = tmp_path / "install"
    (root / "config").mkdir(parents=True)
    (root / "config/production.env").write_text("POSTGRES_PASSWORD=fixture\n")
    docker = DockerDouble()
    monkeypatch.setattr(cli, "run", docker)
    monkeypatch.setattr(cli, "verify_public_health", lambda *a: None)
    # Exercise locking on Linux in integration; Windows lacks fcntl.
    if __import__("os").name == "nt":
        import contextlib

        monkeypatch.setattr(cli, "installation_lock", lambda root: contextlib.nullcontext())
    old = cli.build_bundle(OLD, IMAGES, tmp_path / "old")
    cli.adopt_baseline(
        old, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
    )
    docker.calls.clear()
    new = cli.build_bundle(NEW, IMAGES, tmp_path / "new")
    return root, new, docker


def test_success_commits_only_after_snapshot_preflight_and_health(cli, installation):
    root, new, docker = installation
    cli.deploy(new, root, mode="existing-proxy", monitoring=False, origin="https://example.test")
    assert json.loads((root / "current.json").read_text())["sha"] == NEW
    assert len(list((root / "snapshots").glob("*.dump"))) == 1
    commands = [" ".join(c) for c in docker.calls]
    stop = next(i for i, c in enumerate(commands) if " stop " in c)
    dump = next(i for i, c in enumerate(commands) if "pg_dump" in c)
    restore = next(i for i, c in enumerate(commands) if "pg_restore" in c)
    migrate = next(i for i, c in enumerate(commands) if "run --rm" in c)
    assert stop < dump < restore < migrate
    assert not any("down" in c or "downgrade" in c for c in docker.calls)


@pytest.mark.parametrize(
    "failure",
    [
        "pull",
        "stop",
        "pg_dump",
        "pg_restore",
        "-m dojo.schema",
        "run --rm",
        "--wait-timeout",
    ],
)
def test_failure_preserves_old_state_and_recovers(cli, installation, failure):
    root, new, docker = installation
    docker.fail = failure
    with pytest.raises(RuntimeError):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert json.loads((root / "current.json").read_text())["sha"] == OLD
    assert not docker.stopped
    assert not any("down" in c or "downgrade" in c for c in docker.calls)


def test_missing_baseline_and_unhealthy_baseline_never_interrupt(cli, installation):
    root, new, docker = installation
    docker.unhealthy = True
    with pytest.raises(RuntimeError):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    (root / "current.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert not any("stop" in c for c in docker.calls)


def test_public_health_failure_rolls_back_but_does_not_report_success(
    cli,
    installation,
    monkeypatch,
):
    root, new, docker = installation

    def unavailable(*args):
        raise RuntimeError("HTTPS unavailable")

    monkeypatch.setattr(cli, "verify_public_health", unavailable)
    with pytest.raises(RuntimeError, match="rollback failed"):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert json.loads((root / "current.json").read_text())["sha"] == OLD
    assert not docker.stopped


def test_state_path_escape_is_rejected_before_commands(cli, installation):
    root, new, docker = installation
    state = json.loads((root / "current.json").read_text())
    state["sha"] = "../escape"
    (root / "current.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="commit hash"):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert docker.calls == []


def test_candidate_images_are_not_skipped_because_compose_has_builds(cli, installation):
    root, new, docker = installation
    cli.deploy(new, root, mode="existing-proxy", monitoring=False, origin="https://example.test")
    pull = next(c for c in docker.calls if "pull" in c and "up" not in c)
    assert "--ignore-buildable" not in pull
    assert set(("init", "backend", "worker", "gateway")).issubset(pull)


def test_empty_snapshot_never_migrates(cli, installation, monkeypatch):
    root, new, docker = installation

    def empty_dump(args, **kwargs):
        if "pg_dump" in args:
            docker.calls.append(args)
            return b""
        return docker(args, **kwargs)

    monkeypatch.setattr(cli, "run", empty_dump)
    with pytest.raises(RuntimeError, match="snapshot was empty"):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert not any("init" in c and "run" in c for c in docker.calls)
    assert json.loads((root / "current.json").read_text())["sha"] == OLD
    assert not docker.stopped


def test_signal_during_preflight_restores_prior_services(cli, installation, monkeypatch):
    import signal

    root, new, docker = installation
    original = signal.getsignal(signal.SIGTERM)

    def interrupted(*args):
        signal.raise_signal(signal.SIGTERM)

    monkeypatch.setattr(cli, "preflight", interrupted)
    with pytest.raises(RuntimeError, match="interrupted by signal"):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert not docker.stopped
    assert signal.getsignal(signal.SIGTERM) == original
    assert json.loads((root / "current.json").read_text())["sha"] == OLD


@pytest.mark.skipif(__import__("os").name == "nt", reason="VPS locking requires Linux")
def test_host_lock_rejects_second_deployment(cli, tmp_path):
    with cli.installation_lock(tmp_path):
        with pytest.raises(RuntimeError, match="another deployment"):
            with cli.installation_lock(tmp_path):
                pytest.fail("concurrent deployment entered")


def test_unsupported_compose_fails_before_quiescing(cli, installation, monkeypatch):
    root, new, docker = installation

    def missing_features(args, **kwargs):
        if args == ["docker", "compose", "up", "--help"]:
            return b"old Compose without wait support"
        return docker(args, **kwargs)

    monkeypatch.setattr(cli, "run", missing_features)
    with pytest.raises(RuntimeError, match="Compose lacks"):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert not any("stop" in c for c in docker.calls)


@pytest.mark.parametrize("change", ["volume_name", "mount"])
def test_persistent_storage_changes_are_rejected_before_stop(
    cli, installation, monkeypatch, change
):
    root, new, docker = installation

    def changed_config(args, **kwargs):
        result = docker(args, **kwargs)
        if args[-3:] == ["config", "--format", "json"] and NEW in " ".join(map(str, args)):
            config = json.loads(result)
            if change == "volume_name":
                config["volumes"] = {"media-data": {"name": "empty-new-volume"}}
            else:
                config["services"]["backend"]["volumes"] = [
                    {"type": "bind", "source": "/empty", "target": "/media"},
                ]
            return json.dumps(config).encode()
        return result

    monkeypatch.setattr(cli, "run", changed_config)
    with pytest.raises(ValueError, match="persistent"):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    assert not any("stop" in c for c in docker.calls)


@pytest.mark.parametrize("failure", ["timeout", "signal"])
def test_live_initializer_is_removed_before_old_services_restart(
    cli,
    installation,
    monkeypatch,
    failure,
):
    import signal
    import subprocess

    root, new, docker = installation

    def interrupted(args, **kwargs):
        result = docker(args, **kwargs)
        if "run" in args and "init" in args:
            if failure == "signal":
                signal.raise_signal(signal.SIGTERM)
            raise subprocess.TimeoutExpired("docker", 600)
        return result

    monkeypatch.setattr(cli, "run", interrupted)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        cli.deploy(
            new, root, mode="existing-proxy", monitoring=False, origin="https://example.test"
        )
    live = next(c for c in docker.calls if "run" in c and "init" in c)
    assert "--name" in live
    name = live[live.index("--name") + 1]
    assert name.startswith(cli.PROJECT + "-deploy-init-")
    removed = next(
        i for i, c in enumerate(docker.calls) if c[:3] == ["docker", "rm", "-f"] and c[-1] == name
    )
    restarted = next(i for i, c in enumerate(docker.calls) if "up" in c and "-f" in c)
    assert removed < restarted
    assert json.loads((root / "current.json").read_text())["sha"] == OLD


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.test:99999",
        "https://example.test:0",
        "https://example.test:word",
        "https://bad host",
    ],
)
def test_invalid_origin_fails_before_any_service_commands(cli, installation, origin):
    root, new, docker = installation
    with pytest.raises(ValueError):
        cli.deploy(new, root, mode="existing-proxy", monitoring=False, origin=origin)
    assert not docker.calls


def test_preflight_waits_for_final_tcp_server_not_bootstrap_socket(cli, tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.dump"
    snapshot.write_bytes(b"PGDMPfixture")
    docker = DockerDouble()
    final_server = False

    def bootstrap_server(args, **kwargs):
        nonlocal final_server
        if "pg_isready" in args:
            # Official postgres entrypoint runs a socket-only setup server
            # before creating the database and starting its final TCP server.
            final_server = "-h" in args and args[args.index("-h") + 1] == "127.0.0.1"
        if "pg_restore" in args and not final_server:
            raise RuntimeError("bootstrap server/database not ready for restoration")
        return docker(args, **kwargs)

    monkeypatch.setattr(cli, "run", bootstrap_server)
    cli.preflight(snapshot, IMAGES, IMAGES, "postgres:16-alpine", 5)
    assert final_server
