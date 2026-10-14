#!/usr/bin/env python3
"""Manual authenticated installation recovery. No scheduler or application endpoint."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import deploy

RESERVE = 64 * 1024**2


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
