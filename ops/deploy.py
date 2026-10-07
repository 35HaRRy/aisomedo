#!/usr/bin/env python3
"""Digest-pinned single-VPS releases. No live database restore or volume deletion."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

PROJECT = "dojo-prod"
FILES = (
    "docker-compose.prod.yml",
    "docker-compose.dedicated.yml",
    "docker-compose.existing-proxy.yml",
    "docker-compose.monitoring.yml",
    "deploy.py",
)
SERVICES = ("backend", "worker", "gateway")
SHA = re.compile(r"[0-9a-f]{40}\Z")
IMAGE = re.compile(r"ghcr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}\Z")


def metadata(sha: str, images: dict[str, str]) -> None:
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("release SHA must be a full lowercase commit hash")
    if set(images) != set(SERVICES) or any(
        not isinstance(image, str) or not IMAGE.fullmatch(image) for image in images.values()
    ):
        raise ValueError("exactly three digest-pinned GHCR images are required")


def image_override(images: dict[str, str]) -> dict:
    return {
        "services": {
            name: {"image": images["backend" if name == "init" else name]}
            for name in (*SERVICES, "init")
        }
    }


def build_bundle(sha: str, images: dict[str, str], output: Path) -> Path:
    metadata(sha, images)
    if output.is_symlink() or output.exists():
        raise ValueError("bundle output must be a new directory")
    output.mkdir(parents=True, mode=0o700)
    for name in FILES:
        shutil.copyfile(Path(__file__).resolve().parent / name, output / name)
    (output / "release.json").write_text(
        json.dumps({"sha": sha, "images": images}), encoding="utf-8"
    )
    (output / "images.json").write_text(json.dumps(image_override(images)), encoding="utf-8")
    validate_bundle(output)
    return output


def validate_bundle(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("bundle must be a real directory")
    expected = {*FILES, "release.json", "images.json"}
    if {p.name for p in path.iterdir()} != expected:
        raise ValueError("bundle contains missing or unexpected files")
    if any(p.is_symlink() or not p.is_file() for p in path.iterdir()):
        raise ValueError("bundle files must be regular files, not links")
    info = json.loads((path / "release.json").read_text(encoding="utf-8"))
    if set(info) != {"sha", "images"}:
        raise ValueError("unexpected release metadata")
    metadata(info["sha"], info["images"])
    if json.loads((path / "images.json").read_text(encoding="utf-8")) != image_override(
        info["images"]
    ):
        raise ValueError("image override does not match release digests")
    return info["images"]


def run(args: list[str], *, input=None, stdout=None, timeout=300) -> bytes:
    streamed = hasattr(input, "read")
    result = subprocess.run(
        [str(arg) for arg in args],
        input=None if streamed else input,
        stdin=input if streamed else None,
        stdout=stdout or subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode:
        # Do not echo arguments, Compose config or DB output: they can carry secrets.
        raise RuntimeError(f"{args[0]} command failed (exit {result.returncode})")
    return result.stdout or b""


def options(mode: str, origin: str) -> None:
    parts = urlsplit(origin)
    port = parts.port  # Access performs urllib's numeric/range validation.
    hostname = (parts.hostname or "").encode("idna").decode("ascii").removesuffix(".")
    valid_host = ":" in hostname or (
        len(hostname) <= 253
        and all(
            re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in hostname.split(".")
        )
    )
    if (
        mode not in ("dedicated", "existing-proxy")
        or parts.scheme != "https"
        or not valid_host
        or (port is not None and not 1 <= port <= 65535)
        or (
            not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in ("", "/")
        )
    ):
        raise ValueError("valid deployment mode and public HTTPS origin required")


@contextlib.contextmanager
def installation_lock(root: Path):
    import fcntl  # VPS is Linux; bundle/validate commands also run on other hosts.

    if root.is_symlink() or not root.is_dir():
        raise ValueError("installation root must already exist and not be a symlink")
    with (root / "deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another deployment holds the installation lock") from exc
        yield


def compose(release: Path, root: Path, mode: str, monitoring: bool) -> list[str]:
    env = root / "config/production.env"
    if not env.is_file() or env.is_symlink():
        raise ValueError("missing trusted config/production.env")
    files = [release / "docker-compose.prod.yml", release / f"docker-compose.{mode}.yml"]
    if monitoring:
        files.append(release / "docker-compose.monitoring.yml")
    files.append(release / "images.json")
    return [
        "docker",
        "compose",
        "--env-file",
        str(env),
        "-p",
        PROJECT,
        *[arg for file in files for arg in ("-f", str(file))],
    ]


def installed_bundle(release: Path, root: Path) -> Path:
    validate_bundle(release)
    sha = json.loads((release / "release.json").read_text(encoding="utf-8"))["sha"]
    directory = root / "releases"
    if directory.is_symlink():
        raise ValueError("releases directory must not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / sha
    if target.exists():
        validate_bundle(target)
        if any(
            (target / name).read_bytes() != (release / name).read_bytes()
            for name in (*FILES, "release.json", "images.json")
        ):
            raise ValueError("refusing to overwrite a different recorded release")
    else:
        shutil.copytree(release, target)
    return target


def inspect_container(identifier: str) -> dict:
    return json.loads(run(["docker", "inspect", identifier]))[0]


def running(command: list[str], images: dict[str, str]) -> dict[str, list[str]]:
    ids = {}
    for service in ("db", *SERVICES):
        ids[service] = run(command + ["ps", "--all", "-q", service]).decode().split()
        if not ids[service]:
            raise RuntimeError(f"baseline has no {service} container")
        expected = (
            run(["docker", "image", "inspect", images[service], "--format", "{{.Id}}"])
            .decode()
            .strip()
            if service != "db"
            else None
        )
        for identifier in ids[service]:
            info = inspect_container(identifier)
            if (
                not info["State"]["Running"]
                or info["State"].get("Health", {}).get("Status") != "healthy"
            ):
                raise RuntimeError(f"{service} is not healthy")
            if expected is not None and info["Image"] != expected:
                raise RuntimeError(f"running {service} image differs from recorded release")
    return ids


def write_state(root: Path, release: Path, mode: str, monitoring: bool, origin: str) -> None:
    state = {
        "sha": json.loads((release / "release.json").read_text())["sha"],
        "mode": mode,
        "monitoring": monitoring,
        "origin": origin,
    }
    temporary = root / "current.json.tmp"
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, root / "current.json")


def verify_public_health(origin: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(origin.rstrip("/") + "/ready", timeout=5) as response:
                if response.status != 200 or json.load(response).get("status") != "ok":
                    raise ValueError("invalid readiness response")
            with urllib.request.urlopen(
                origin.rstrip("/") + "/web-health.txt", timeout=5
            ) as response:
                if response.status != 200 or not response.read().strip():
                    raise ValueError("empty web health response")
            return
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise RuntimeError("public HTTPS health verification failed") from None
            time.sleep(2)


def adopt_baseline(release: Path, root: Path, *, mode: str, monitoring: bool, origin: str) -> None:
    options(mode, origin)
    with installation_lock(root):
        if (root / "current.json").exists():
            raise ValueError("baseline already recorded")
        images = validate_bundle(release)
        running(compose(release, root, mode, monitoring), images)
        verify_public_health(origin, 180)
        release = installed_bundle(release, root)
        write_state(root, release, mode, monitoring, origin)


def preflight(
    snapshot: Path,
    images: dict[str, str],
    previous_images: dict[str, str],
    database_image: str,
    timeout: int,
) -> None:
    token = secrets.token_hex(8)
    network = f"dojo-preflight-{token}"
    db, smoke, migrate = (network + suffix for suffix in ("-db", "-smoke", "-migrate"))
    password = secrets.token_hex(24)
    # No production credentials or media mounts; this network has no external access.
    with tempfile.TemporaryDirectory(prefix="dojo-preflight-") as scratch:
        env_file = Path(scratch) / "preflight.env"
        env_file.write_text(
            f"POSTGRES_PASSWORD={password}\nPOSTGRES_USER=dojo\nPOSTGRES_DB=dojo\n"
            f"DATABASE_URL=postgresql+psycopg://dojo:{password}@{db}:5432/dojo\n"
            "SKIP_CREATE_ALL=1\nSIGNED_URL_SECRET=preflight-only\n"
            "PUBLIC_BASE_URL=https://preflight.invalid\nCOOKIE_SECURE=true\n"
            "MEDIA_ROOT=/tmp/preflight-media\n",
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        try:
            run(["docker", "network", "create", "--internal", network])
            run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    db,
                    "--network",
                    network,
                    "--env-file",
                    str(env_file),
                    database_image,
                ]
            )
            deadline = time.monotonic() + timeout
            while True:
                try:
                    run(
                        [
                            "docker",
                            "exec",
                            db,
                            "pg_isready",
                            "-h",
                            "127.0.0.1",
                            "-U",
                            "dojo",
                            "-d",
                            "dojo",
                        ]
                    )
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("preflight PostgreSQL readiness timed out") from None
                    time.sleep(1)
            with snapshot.open("rb") as data:
                run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        db,
                        "pg_restore",
                        "--exit-on-error",
                        "--no-owner",
                        "--no-acl",
                        "-U",
                        "dojo",
                        "-d",
                        "dojo",
                    ],
                    input=data,
                    timeout=timeout,
                )
            run(
                [
                    "docker",
                    "run",
                    "--name",
                    migrate,
                    "--network",
                    network,
                    "--env-file",
                    str(env_file),
                    images["backend"],
                    ".venv/bin/python",
                    "-m",
                    "dojo.schema",
                ],
                timeout=timeout,
            )
            run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    smoke,
                    "--network",
                    network,
                    "--env-file",
                    str(env_file),
                    previous_images["backend"],
                ]
            )
            deadline = time.monotonic() + timeout
            probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=4)"
            while True:
                try:
                    run(["docker", "exec", smoke, ".venv/bin/python", "-c", probe])
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("previous backend rejects migrated snapshot") from None
                    time.sleep(2)
        finally:
            # Exact random names owned by this invocation; -v only removes their
            # anonymous preflight volumes, never any Compose production volume.
            for name in (smoke, migrate, db):
                try:
                    run(["docker", "rm", "-f", "-v", name])
                except RuntimeError:
                    # A failure before creation leaves no container to remove.
                    if run(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"]).strip():
                        raise RuntimeError("preflight container cleanup failed") from None
            try:
                run(["docker", "network", "rm", network])
            except RuntimeError:
                if run(["docker", "network", "ls", "-q", "--filter", f"name=^{network}$"]).strip():
                    raise RuntimeError("preflight network cleanup failed") from None


def deploy(
    release: Path,
    root: Path,
    *,
    mode: str,
    monitoring: bool,
    origin: str,
    health_timeout: int = 180,
) -> None:
    options(mode, origin)
    if health_timeout <= 0:
        raise ValueError("health timeout must be positive")
    with installation_lock(root):
        state_path = root / "current.json"
        if state_path.is_symlink():
            raise ValueError("state must not be a symlink")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state.get("sha"), str) or not SHA.fullmatch(state["sha"]):
            raise ValueError("recorded release must use a full lowercase commit hash")
        metadata(state["sha"], validate_bundle(root / "releases" / state["sha"]))
        options(state["mode"], state["origin"])
        previous = root / "releases" / state["sha"]
        old_images = validate_bundle(previous)
        images = validate_bundle(release)
        release = installed_bundle(release, root)
        old = compose(previous, root, state["mode"], state["monitoring"])
        new = compose(release, root, mode, monitoring)
        help_text = run(["docker", "compose", "up", "--help"]).decode()
        if any(option not in help_text for option in ("--wait-timeout", "--no-deps", "--pull")):
            raise RuntimeError("Compose lacks required rollout/rollback features")
        ids = running(old, old_images)
        old_config = json.loads(run(old + ["config", "--format", "json"]))
        config = json.loads(run(new + ["config", "--format", "json"]))
        if config["services"]["db"] != old_config["services"]["db"]:
            raise ValueError("automatic releases must not change the database service")
        if config.get("volumes", {}) != old_config.get("volumes", {}) or any(
            config["services"].get(service, {}).get("volumes", [])
            != old_config["services"].get(service, {}).get("volumes", [])
            for service in ("db", "init", *SERVICES)
        ):
            raise ValueError("automatic releases must not change persistent storage identities")
        for service in SERVICES:
            if config["services"].get(service, {}).get("image", images[service]) != images[service]:
                raise ValueError("rendered candidate does not match recorded images")
        run(new + ["pull", *SERVICES, "init"], timeout=600)
        env = config["services"]["db"]["environment"]
        user, database = env["POSTGRES_USER"], env["POSTGRES_DB"]
        db = ids["db"][0]
        size = int(
            run(
                [
                    "docker",
                    "exec",
                    db,
                    "psql",
                    "-U",
                    user,
                    "-d",
                    database,
                    "-tAc",
                    "SELECT pg_database_size(current_database())",
                ]
            ).strip()
        )
        snapshots = root / "snapshots"
        if snapshots.is_symlink():
            raise ValueError("snapshot directory must not be a symlink")
        snapshots.mkdir(mode=0o700, exist_ok=True)
        snapshots.chmod(0o700)
        if shutil.disk_usage(snapshots).free < 2 * size + 1024**3:
            raise RuntimeError("insufficient space for snapshot and rehearsal")
        sha = json.loads((release / "release.json").read_text())["sha"]
        snapshot = snapshots / f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}-{sha}.dump"
        interrupted = False
        live_init = f"{PROJECT}-deploy-init-{secrets.token_hex(8)}"
        initializer_started = False
        handlers = {}

        def abort(signum, frame):
            raise RuntimeError(f"deployment interrupted by signal {signum}")

        for signum in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
            if signum not in handlers:
                handlers[signum] = signal.signal(signum, abort)
        try:
            interrupted = True  # A failed stop can already have stopped one service.
            run(old + ["stop", "backend", "worker"], timeout=300)
            for service in ("backend", "worker"):
                if any(
                    inspect_container(identifier)["State"]["Running"] for identifier in ids[service]
                ):
                    raise RuntimeError("could not quiesce application services")
            with snapshot.open("xb") as output:
                snapshot.chmod(0o600)
                run(
                    [
                        "docker",
                        "exec",
                        db,
                        "pg_dump",
                        "--format=custom",
                        "-U",
                        user,
                        "-d",
                        database,
                    ],
                    stdout=output,
                    timeout=600,
                )
                output.flush()
                os.fsync(output.fileno())
            if snapshot.stat().st_size == 0:
                raise RuntimeError("snapshot was empty")
            preflight(snapshot, images, old_images, inspect_container(db)["Image"], health_timeout)
            initializer_started = True
            run(
                new
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "--name",
                    live_init,
                    "-e",
                    f"PGAPPNAME={live_init}",
                    "init",
                ],
                timeout=600,
            )
            initializer_started = False
            start = [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                str(health_timeout),
                *SERVICES,
            ]
            run(new + start, timeout=health_timeout + 60)
            running(new, images)
            verify_public_health(origin, health_timeout)
            write_state(root, release, mode, monitoring, origin)
        except BaseException as original:
            if interrupted:
                # Do not let a repeated HUP/TERM interrupt recovery halfway through.
                for signum in handlers:
                    signal.signal(signum, signal.SIG_IGN)
                try:
                    if initializer_started:
                        # CLI death does not stop a detached Docker process or
                        # server-side SQL. End this invocation's initializer and
                        # uniquely tagged DB sessions before restarting any app.
                        container_filter = [
                            "docker",
                            "ps",
                            "-aq",
                            "--filter",
                            f"name=^/{live_init}$",
                        ]
                        try:
                            run(["docker", "rm", "-f", live_init])
                        except RuntimeError:
                            if run(container_filter).strip():
                                raise RuntimeError("live initializer termination failed") from None
                        if run(container_filter).strip():
                            raise RuntimeError("live initializer still exists")
                        query = ["docker", "exec", db, "psql", "-U", user, "-d", database, "-tAc"]
                        predicate = f"application_name = '{live_init}' AND pid <> pg_backend_pid()"
                        run(
                            query
                            + [
                                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE "
                                + predicate
                            ]
                        )
                        deadline = time.monotonic() + 10
                        while int(
                            run(
                                query + ["SELECT count(*) FROM pg_stat_activity WHERE " + predicate]
                            ).strip()
                        ):
                            if time.monotonic() >= deadline:
                                raise RuntimeError(
                                    "live initializer database sessions did not exit"
                                )
                            time.sleep(0.2)
                    run(new + ["stop", "backend", "worker"], timeout=300)
                    run(
                        old
                        + [
                            "up",
                            "-d",
                            "--no-build",
                            "--pull",
                            "never",
                            "--no-deps",
                            "--wait",
                            "--wait-timeout",
                            str(health_timeout),
                            *SERVICES,
                        ],
                        timeout=health_timeout + 60,
                    )
                    running(old, old_images)
                    verify_public_health(state["origin"], health_timeout)
                except BaseException as recovery:
                    raise RuntimeError(
                        f"deployment failed; rollback failed: {recovery}"
                    ) from original
            raise
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--sha", required=True)
    for service in SERVICES:
        bundle.add_argument(f"--{service}", required=True)
    bundle.add_argument("--output", required=True, type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("--release", required=True, type=Path)
    for name in ("adopt", "deploy"):
        command = commands.add_parser(name)
        command.add_argument("--release", required=True, type=Path)
        command.add_argument("--root", required=True, type=Path)
        command.add_argument("--mode", choices=("dedicated", "existing-proxy"), required=True)
        command.add_argument("--monitoring", action="store_true")
        command.add_argument("--origin", required=True)
    args = vars(parser.parse_args())
    name = args.pop("command")
    try:
        if name == "bundle":
            build_bundle(args["sha"], {s: args[s] for s in SERVICES}, args["output"])
        elif name == "validate":
            validate_bundle(args["release"])
        else:
            (adopt_baseline if name == "adopt" else deploy)(**args)
    except (ValueError, OSError, RuntimeError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"Release {name} failed: {exc}")
        return 1
    print(f"Release {name} succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
