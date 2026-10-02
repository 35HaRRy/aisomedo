"""Manifest-bound private artifacts; no directory browsing or public signing."""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from dojo.exceptions import MediaNotFound
from dojo.model import PackageArtifact


def extension_for(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/heif": ".heif", "video/mp4": ".mp4",
        "video/quicktime": ".mov",
    }.get(content_type, "")


def _filename(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(c for c in name if ord(c) >= 32) or "media"


def _known_artifacts(manifest: dict) -> list[dict]:
    artifacts: list[dict] = []
    for entry in manifest.get("media", []):
        mid = str(entry.get("media_id", ""))
        if not mid or any(c in mid for c in "/\\:") or mid in (".", ".."):
            continue
        if entry.get("status") not in ("finalized", "removed"):
            continue
        prefix = "removed" if entry["status"] == "removed" else "media"
        filename = _filename(str(entry.get("filename", "media")))
        content_type = str(entry.get("content_type", "application/octet-stream"))
        suffix = Path(filename).suffix or extension_for(content_type)
        artifacts.append({
            "artifact_ref": f"{prefix}/{mid}/original{suffix}", "kind": "original",
            "filename": filename, "content_type": content_type, "valid": True,
        })
        processed = entry.get("processed", {})
        processed_type = str(processed.get("content_type", ""))
        processed_suffix = extension_for(processed_type)
        basename = f"processed{processed_suffix}"
        valid = bool(processed_suffix) and processed.get("path") in (
            f"media/{mid}/{basename}", f"removed/{mid}/{basename}",
        )
        artifacts.append({
            "artifact_ref": f"{prefix}/{mid}/{basename}", "kind": "processed",
            "filename": f"{Path(filename).stem}.processed{processed_suffix}",
            "content_type": processed_type or "application/octet-stream", "valid": valid,
        })
    artifacts.append({
        "artifact_ref": "render/reel.mp4", "kind": "render", "filename": "reel.mp4",
        "content_type": "video/mp4", "valid": True,
    })
    return artifacts


def _contained_path(root: Path, reference: str) -> Path:
    posix, windows = PurePosixPath(reference), PureWindowsPath(reference)
    if not reference or "\\" in reference or posix.is_absolute() or windows.drive or (
        any(part in (".", "..") for part in reference.split("/"))
    ):
        raise ValueError("artifact reference must be a package-relative canonical path")
    resolved_root = root.resolve()
    if not resolved_root.is_relative_to(root.parent.resolve()):
        raise ValueError("package storage escapes media root")
    candidate = (resolved_root / reference).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("artifact reference escapes package storage")
    return candidate


def describe_artifacts(root: Path, manifest: dict) -> list[dict]:
    result = []
    for spec in _known_artifacts(manifest):
        try:
            available = spec["valid"] and _contained_path(root, spec["artifact_ref"]).is_file()
        except (ValueError, OSError):
            available = False
        result.append({**{key: value for key, value in spec.items() if key != "valid"},
                       "available": bool(available)})
    return result


def resolve_artifact(root: Path, manifest: dict, artifact_ref: str) -> PackageArtifact:
    candidate = _contained_path(root, artifact_ref)
    spec = next((item for item in _known_artifacts(manifest)
                 if item["artifact_ref"] == artifact_ref and item["valid"]), None)
    if spec is None or not candidate.is_file():
        raise MediaNotFound("package artifact is unavailable")
    return PackageArtifact(path=candidate, filename=spec["filename"],
                           content_type=spec["content_type"])


def public_media(entry: dict) -> dict:
    """Keep ordinary manifest metadata, but never disclose internal absolute paths."""
    result = {key: entry[key] for key in (
        "media_id", "filename", "content_type", "size_bytes", "uploaded_at", "status",
        "removed_position",
    ) if key in entry}
    processed = entry.get("processed", {})
    result["processed"] = {key: processed[key] for key in (
        "content_type", "size_bytes", "dimensions", "duration",
    ) if key in processed}
    mid = entry.get("media_id")
    basename = f"processed{extension_for(str(processed.get('content_type', '')))}"
    if processed.get("path") in (f"media/{mid}/{basename}", f"removed/{mid}/{basename}"):
        result["processed"]["path"] = processed["path"]
    return result
