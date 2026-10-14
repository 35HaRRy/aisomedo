#!/usr/bin/env python3
"""Manual authenticated installation recovery. No scheduler or application endpoint."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import deploy

RESERVE = 64 * 1024**2

# Helpers run in the already-installed backend image with only the chosen volume.
MEDIA_SCAN = """
import hashlib, json, stat, sys, tarfile
from pathlib import Path
root = Path('/media')
paths = [root, *sorted(root.rglob('*'))]
inventory = {}
for path in paths:
    mode = path.lstat().st_mode
    name = path.relative_to(root.parent).as_posix()
    if stat.S_ISDIR(mode):
        inventory[name] = {'type': 'directory'}
    elif stat.S_ISREG(mode):
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        inventory[name] = {'type': 'file', 'size': path.stat().st_size, 'sha256': checksum}
    else:
        raise ValueError('unsupported media file type')
"""
MEDIA_EXPORT = MEDIA_SCAN + """
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for path in paths:
        archive.add(path, arcname=path.relative_to(root.parent).as_posix(), recursive=False)
"""
MEDIA_INVENTORY = MEDIA_SCAN + "print(json.dumps(inventory))"


def trusted(path: Path) -> None:
    if path.resolve() != path.absolute():
        raise ValueError("trusted installation path must not contain links or traversal")


def volume_helper(installation: dict[str, Any], script: str, *,
                  output: Any = None, input: Any = None, writable: bool = False) -> bytes:
    name = f"{deploy.PROJECT}-recovery-{secrets.token_hex(8)}"
    mount = f"type=volume,src={installation['media_volume']},dst=/media"
    if not writable:
        mount += ",readonly"
    try:
        return deploy.run(
            ["docker", "run", "--rm", "--pull", "never", "--name", name,
             "--network", "none", "--read-only", "-i", "--mount", mount,
             "--entrypoint", ".venv/bin/python", installation["images"]["backend"],
             "-c", script], input=input, stdout=output, timeout=3600,
            step="selected media volume operation (docker run)",
        )
    finally:
        try:
            deploy.run(["docker", "rm", "-f", name], step="media helper cleanup (docker rm)")
        except RuntimeError:
            if deploy.run(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
                          step="media helper cleanup verification (docker ps)").strip():
                raise RuntimeError("media helper cleanup failed") from None


def query(installation: dict[str, Any], sql: str) -> bytes:
    env = installation["config"]["services"]["db"]["environment"]
    return deploy.run(["docker", "exec", installation["containers"]["db"][0],
                       "psql", "-U", env["POSTGRES_USER"], "-d", env["POSTGRES_DB"],
                       "-v", "ON_ERROR_STOP=1", "-tAc", sql],
                      step="database verification query (docker exec)")


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def database_metadata(installation: dict[str, Any]) -> dict[str, Any]:
    tables = json.loads(query(installation,
        "SELECT coalesce(json_agg(json_build_object('schema', schemaname, 'table', tablename) "
        "ORDER BY schemaname, tablename), '[]'::json) FROM pg_tables "
        "WHERE schemaname NOT LIKE 'pg_%' AND schemaname <> 'information_schema'"))
    for table in tables:
        qualified = identifier(table["schema"]) + "." + identifier(table["table"])
        table["rows"] = int(query(installation, f"SELECT count(*) FROM {qualified}").strip())
    schema = json.loads(query(installation,
        "SELECT coalesce(json_agg(version_num ORDER BY version_num), '[]'::json) "
        "FROM public.alembic_version"))
    major = query(installation,
                  "SELECT current_setting('server_version_num')::int / 10000").decode().strip()
    image = deploy.inspect_container(installation["containers"]["db"][0])["Image"]
    return {"image": image, "major": major, "tables": tables, "schema_version": schema}


def read_installation(root: Path) -> dict[str, Any]:
    trusted(root)
    for path in (root / "config", root / "current.json", root / "config/production.env",
                 root / "releases"):
        trusted(path)
    regular(root / "current.json")
    state = json.loads((root / "current.json").read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or set(state) != {"sha", "mode", "monitoring", "origin"}
            or not isinstance(state["sha"], str) or not deploy.SHA.fullmatch(state["sha"])
            or type(state["monitoring"]) is not bool):
        raise ValueError("invalid recorded installation state")
    deploy.options(state["mode"], state["origin"])
    release = root / "releases" / state["sha"]
    trusted(release)
    images = deploy.validate_bundle(release)
    # Shell interpolation overrides would make the archived env file unreproducible.
    variables = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", "\n".join(
        (release / name).read_text() for name in deploy.FILES if name.endswith(".yml"))))
    if variables.intersection(os.environ):
        raise ValueError("unset Compose interpolation variables from the shell before recovery")
    command = deploy.compose(release, root, state["mode"], state["monitoring"])
    config = json.loads(deploy.run(command + ["config", "--format", "json"],
                                   step="recovery configuration (docker compose config)"))
    containers = deploy.running(command, images)
    if len(containers["db"]) != 1:
        raise ValueError("exactly one database container is required")
    initializers = deploy.run(command + ["ps", "--all", "-q", "init"],
                               step="initializer inspection (docker compose ps)").decode().split()
    if any(deploy.inspect_container(name)["State"]["Running"] for name in initializers):
        raise RuntimeError("active schema initializer prevents recovery")
    media_volumes = set()
    for service in ("backend", "worker"):
        for container in containers[service]:
            info = deploy.inspect_container(container)
            mounts = [m for m in info["Mounts"] if m["Destination"] == "/media"]
            if len(mounts) != 1 or mounts[0]["Type"] != "volume":
                raise ValueError("media must use one durable named volume")
            media_volumes.add(mounts[0]["Name"])
    if len(media_volumes) != 1:
        raise ValueError("all writers must share the selected media volume")
    media_volume = media_volumes.pop()
    if media_volume != config["volumes"]["media-data"]["name"]:
        raise ValueError("runtime media storage differs from recorded configuration")
    db_info = deploy.inspect_container(containers["db"][0])
    db_mounts = [m for m in db_info["Mounts"] if m["Destination"].startswith("/var/lib/postgresql")]
    if len(db_mounts) != 1 or db_mounts[0]["Type"] != "volume":
        raise ValueError("database must use one durable named volume")
    if db_mounts[0]["Name"] != config["volumes"]["db-data"]["name"]:
        raise ValueError("runtime database storage differs from recorded configuration")
    for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"):
        if f"{key}={config['services']['db']['environment'][key]}" not in db_info["Config"]["Env"]:
            raise ValueError("database runtime differs from recorded configuration")
    secret = None
    if state["monitoring"]:
        secret = Path(config["secrets"]["firebase_credentials"]["file"])
        trusted(secret)
        regular(secret)
    installation = {"root": root, "state": state, "release": release, "images": images,
                    "command": command, "config": config, "containers": containers,
                    "media_volume": media_volume, "worker_count": len(containers["worker"]),
                    "backend_count": len(containers["backend"]), "credential": secret}
    inventory = json.loads(volume_helper(installation, MEDIA_INVENTORY))
    media_size = sum(entry.get("size", 0) for entry in inventory.values())
    database_size = int(query(installation, "SELECT pg_database_size(current_database())"))
    installation["required_space"] = 4 * (media_size + database_size) + RESERVE
    return installation


def file_inventory(root: Path) -> dict[str, Any]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("unsupported payload file type")
        name = path.relative_to(root).as_posix()
        result[name] = ({"type": "directory"} if path.is_dir() else
                        {"type": "file", "size": path.stat().st_size, "sha256": digest(path)})
    return result


def capture_archive(installation: dict[str, Any], staging: Path) -> Path:
    payload = staging / "payload"
    private_directory(payload)
    private_directory(payload / "config")
    root = installation["root"]
    shutil.copyfile(root / "config/production.env", payload / "config/production.env")
    shutil.copyfile(root / "current.json", payload / "current.json")
    shutil.copytree(installation["release"], payload / "release")
    credentials = {}
    if installation["credential"]:
        private_directory(payload / "credentials")
        shutil.copyfile(installation["credential"], payload / "credentials/firebase.json")
        credentials["firebase_credentials"] = "credentials/firebase.json"
    env = installation["config"]["services"]["db"]["environment"]
    with (payload / "database.dump").open("xb") as output:
        (payload / "database.dump").chmod(0o600)
        deploy.run(["docker", "exec", installation["containers"]["db"][0], "pg_dump",
                    "--format=custom", "-U", env["POSTGRES_USER"], "-d", env["POSTGRES_DB"]],
                   stdout=output, timeout=3600, step="recovery database dump (docker exec)")
    if not (payload / "database.dump").stat().st_size:
        raise RuntimeError("database dump was empty")
    media_tar = staging / "media.tar"
    with media_tar.open("xb") as output:
        media_tar.chmod(0o600)
        volume_helper(installation, MEDIA_EXPORT, output=output)
    with tarfile.open(media_tar, "r:") as tar:
        seen = set()
        for entry in tar:
            name = member_name(entry.name)
            if (not name.startswith("media/") and name != "media") or name in seen or not (
                entry.isdir() or entry.isfile()
            ):
                raise ValueError("unsafe media export")
            seen.add(name)
            target = payload / name
            if entry.isdir():
                private_directory(target)
            else:
                private_directory(target.parent)
                stream = tar.extractfile(entry)
                assert stream is not None
                with stream, target.open("xb") as output:
                    target.chmod(0o600)
                    shutil.copyfileobj(stream, output)
    media_tar.unlink()
    manifest = {"version": 1, "created_at": datetime.now(UTC).isoformat(),
                "state": installation["state"], "database": database_metadata(installation),
                "files": file_inventory(payload), "credentials": credentials}
    validate_manifest(manifest)
    (payload / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for path in payload.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    archive = staging / "recovery.tar"
    with tarfile.open(archive, "w") as tar:
        archive.chmod(0o600)
        for path in sorted(payload.rglob("*")):
            tar.add(path, arcname=path.relative_to(payload).as_posix(), recursive=False)
    return archive


@contextlib.contextmanager
def interruption_handlers() -> Any:
    handlers = {}

    def abort(signum: int, frame: Any) -> None:
        raise RuntimeError(f"recovery interrupted by signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
        if signum not in handlers:
            handlers[signum] = signal.signal(signum, abort)
    try:
        yield handlers
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def stop_writers(installation: dict[str, Any]) -> None:
    deploy.run(installation["command"] + ["stop", "backend", "worker"], timeout=300,
               step="recovery quiesce (docker compose stop)")
    for service in ("backend", "worker"):
        for name in installation["containers"][service]:
            if deploy.inspect_container(name)["State"]["Running"]:
                raise RuntimeError("application writer did not stop")


def start_writers(installation: dict[str, Any]) -> None:
    deploy.run(installation["command"] + ["up", "-d", "--no-build", "--pull", "never",
               "--no-deps", "--scale", f"worker={installation['worker_count']}",
               "--scale", f"backend={installation.get('backend_count', 1)}", "--wait",
               "--wait-timeout", "180", *deploy.SERVICES], timeout=240,
               step="recovery application start (docker compose up)")
    deploy.running(installation["command"], installation["images"])
    deploy.verify_public_health(installation["state"]["origin"], 180)


def preflight_backup(root: Path, recipient: str, output: Path, staging: Path,
                     installation: dict[str, Any]) -> None:
    new_output(output)
    space(staging, installation.get("required_space", RESERVE))
    space(output.parent, installation.get("required_space", RESERVE))
    trusted(output.parent)
    if installation.get("media_volume"):
        mount = json.loads(deploy.run(
            ["docker", "volume", "inspect", installation["media_volume"]],
            step="backup output containment (docker volume inspect)") or b"[]")
        if mount:
            location = Path(mount[0]["Mountpoint"])
            if output.resolve().is_relative_to(location.resolve()):
                raise ValueError("backup output must be outside selected media")
    probe = staging / "recipient-probe"
    probe.write_bytes(b"")
    encrypt_archive(probe, recipient, staging / "recipient-probe.age")


def backup(root: Path, recipient: str, output: Path) -> None:
    with deploy.installation_lock(root):
        installation = read_installation(root)
        with tempfile.TemporaryDirectory(prefix=".dojo-backup-", dir=root) as scratch:
            staging = Path(scratch)
            staging.chmod(0o700)
            preflight_backup(root, recipient, output, staging, installation)
            with interruption_handlers() as handlers:
                attempted_stop = False
                try:
                    attempted_stop = True
                    stop_writers(installation)
                    archive = capture_archive(installation, staging)
                    encrypt_archive(archive, recipient, output)
                except BaseException as original:
                    if attempted_stop:
                        for signum in handlers:
                            signal.signal(signum, signal.SIG_IGN)
                        try:
                            start_writers(installation)
                        except BaseException:
                            raise RuntimeError(
                                "backup failed; application recovery also failed; "
                                "check service health before retrying"
                            ) from original
                    raise
                else:
                    start_writers(installation)


def regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("a regular non-link file is required")


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("directory must not be a link")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def space(path: Path, size: int) -> None:
    if shutil.disk_usage(path).free < size + RESERVE:
        raise RuntimeError("insufficient private staging space")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def new_output(path: Path) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("output must be a new file in an existing directory")
    if path.parent.resolve() != path.parent.absolute():
        raise ValueError("output parent must not contain links or relative traversal")


def age_file(source: Path, output: Path, arguments: list[str]) -> None:
    regular(source)
    new_output(output)
    space(output.parent, source.stat().st_size + 1024**2)
    with tempfile.TemporaryDirectory(prefix=".dojo-age-", dir=output.parent) as scratch:
        folder = Path(scratch)
        folder.chmod(0o700)
        temporary = folder / "output"
        with temporary.open("xb") as stream:
            temporary.chmod(0o600)
            deploy.run(["age", *arguments, str(source)], stdout=stream,
                       timeout=3600, step="authenticated archive processing (age)")
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails if another process created output.
        os.link(temporary, output)
        if os.name == "posix":
            descriptor = os.open(output.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def encrypt_archive(archive: Path, recipient: str, output: Path) -> None:
    if not re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", recipient):
        raise ValueError("native age public recipient required")
    age_file(archive, output, ["--encrypt", "--recipient", recipient])


def decrypt_archive(archive: Path, identity: Path, output: Path) -> None:
    regular(identity)
    age_file(archive, output, ["--decrypt", "--identity", str(identity)])


def member_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or "\x00" in name
            or path.is_absolute() or any(p in (".", "..", "") for p in name.split("/"))
            or path.as_posix() != name):
        raise ValueError("unsafe archive member")
    if name not in ("manifest.json", "database.dump", "current.json") and path.parts[0] not in (
        "config", "release", "credentials", "media"
    ):
        raise ValueError("unexpected archive member")
    return name


def validate_manifest(manifest: dict[str, Any]) -> None:
    if (not isinstance(manifest, dict)
            or set(manifest) != {"version", "created_at", "state", "database", "files",
                                 "credentials"}
            or type(manifest["version"]) is not int or manifest["version"] != 1
            or not isinstance(manifest["created_at"], str)):
        raise ValueError("unsupported archive manifest")
    state = manifest["state"]
    if (not isinstance(state, dict) or set(state) != {"sha", "mode", "monitoring", "origin"}
            or not isinstance(state["sha"], str) or not deploy.SHA.fullmatch(state["sha"])
            or type(state["monitoring"]) is not bool):
        raise ValueError("invalid archived deployment state")
    deploy.options(state["mode"], state["origin"])
    database = manifest["database"]
    if (not isinstance(database, dict)
            or set(database) != {"image", "major", "tables", "schema_version"}
            or not isinstance(database["image"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", database["image"])
            or not isinstance(database["major"], str)
            or not re.fullmatch(r"[0-9]{1,2}", database["major"])
            or not isinstance(database["tables"], list)
            or not isinstance(database["schema_version"], list)
            or any(not isinstance(v, str) for v in database["schema_version"])):
        raise ValueError("invalid archived database metadata")
    names = set()
    for table in database["tables"]:
        if (not isinstance(table, dict) or set(table) != {"schema", "table", "rows"}
                or not all(isinstance(table[k], str) and table[k] for k in ("schema", "table"))
                or type(table["rows"]) is not int or table["rows"] < 0):
            raise ValueError("invalid table verification metadata")
        table_name = (table["schema"], table["table"])
        if table_name in names:
            raise ValueError("duplicate table verification metadata")
        names.add(table_name)
    if (not isinstance(manifest["files"], dict)
            or not isinstance(manifest["credentials"], dict)
            or set(manifest["credentials"]) not in (set(), {"firebase_credentials"})):
        raise ValueError("invalid archive inventory")
    if bool(manifest["credentials"]) != state["monitoring"]:
        raise ValueError("monitoring credential inventory mismatch")
    for name, entry in manifest["files"].items():
        member_name(name)
        if name == "manifest.json" or not isinstance(entry, dict):
            raise ValueError("invalid payload inventory entry")
        if entry == {"type": "directory"}:
            continue
        if (set(entry) != {"type", "size", "sha256"} or entry["type"] != "file"
                or type(entry["size"]) is not int or entry["size"] < 0
                or not isinstance(entry["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("invalid file verification metadata")
    required = {"database.dump", "current.json", "config", "config/production.env",
                "release", "media"}
    if not required <= manifest["files"].keys():
        raise ValueError("missing required recovery payload")
    for name in ("database.dump", "current.json", "config/production.env"):
        if manifest["files"][name]["type"] != "file":
            raise ValueError("required payload is not a regular file")
    for name in ("config", "release", "media"):
        if manifest["files"][name]["type"] != "directory":
            raise ValueError("required payload is not a directory")
    expected_config = {"config", "config/production.env"}
    if {n for n in manifest["files"] if n.split("/")[0] == "config"} != expected_config:
        raise ValueError("unexpected configuration payload")
    for name in manifest["credentials"].values():
        if name != "credentials/firebase.json" or manifest["files"].get(name, {}).get(
            "type"
        ) != "file":
            raise ValueError("invalid secret payload")


def validate_archive(archive: Path, staging: Path) -> dict[str, Any]:
    regular(archive)
    if staging.exists() or staging.is_symlink():
        raise ValueError("archive staging must be a new directory")
    private_directory(staging)
    try:
        with tarfile.open(archive, "r:") as tar:
            members: dict[str, tarfile.TarInfo] = {}
            for entry in tar:
                name = member_name(entry.name)
                if name in members or not (entry.isfile() or entry.isdir()) or entry.size < 0:
                    raise ValueError("duplicate or unsupported archive member")
                if len(members) >= 1000000:
                    raise ValueError("archive inventory is too large")
                members[name] = entry
            metadata = members.get("manifest.json")
            if not metadata or not metadata.isfile() or metadata.size > 8 * 1024**2:
                raise ValueError("missing or oversized archive manifest")
            source = tar.extractfile(metadata)
            assert source is not None
            manifest = json.load(source)
            validate_manifest(manifest)
            if set(members) != {"manifest.json", *manifest["files"]}:
                raise ValueError("archive inventory differs from manifest")
            total = sum(entry.size for entry in members.values())
            space(staging, total)
            for name, entry in sorted(members.items()):
                expected = manifest["files"].get(name)
                if expected and (entry.isdir() != (expected["type"] == "directory")
                                 or (entry.isfile() and entry.size != expected["size"])):
                    raise ValueError("archive member size or type mismatch")
                target = staging / name
                if entry.isdir():
                    private_directory(target)
                else:
                    private_directory(target.parent)
                    stream = tar.extractfile(entry)
                    assert stream is not None
                    with stream, target.open("xb") as output:
                        target.chmod(0o600)
                        shutil.copyfileobj(stream, output)
                    if expected and digest(target) != expected["sha256"]:
                        raise ValueError("archive member checksum mismatch")
            if json.loads((staging / "current.json").read_text()) != manifest["state"]:
                raise ValueError("state payload differs from manifest")
            deploy.validate_bundle(staging / "release")
            if json.loads((staging / "release/release.json").read_text())["sha"] != manifest[
                "state"
            ]["sha"]:
                raise ValueError("release payload differs from manifest")
            return manifest
    except BaseException:
        # Only this invocation's newly created extraction directory is removed.
        shutil.rmtree(staging)
        raise
