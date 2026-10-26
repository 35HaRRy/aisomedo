"""Pure package content comparison and derived manifest export."""

import json
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from dojo.exceptions import MontageTrimInvalid, PackageEditConflict
from dojo.montage import manifest_selections, source_duration, validate_ranges


@dataclass(frozen=True)
class GroupEdit:
    key: str
    base: dict
    proposed: dict


def _validate_group_value(key: str, value: dict, media: dict | None) -> None:
    field = ("ranges" if key.startswith("video:") else "seconds" if key.startswith("photo:")
             else {"order": "ids", "caption": "text", "branding": "settings"}.get(key))
    if field is None or not isinstance(value, dict) or set(value) != {field}:
        raise MontageTrimInvalid("invalid edit group shape")
    item = value[field]
    if field == "ranges":
        if not isinstance(item, list):
            raise MontageTrimInvalid("ranges must be a list")
        if item:
            validate_ranges(item, source_duration(media or {}) or 0)
    elif field == "seconds":
        if isinstance(item, bool) or not isinstance(item, (int, float)) \
                or not isfinite(item) or item < 1 / 25:
            raise MontageTrimInvalid("photo duration must be finite and at least one frame")
    elif field == "ids":
        if not isinstance(item, list) or any(not isinstance(i, str) for i in item) \
                or len(item) != len(set(item)):
            raise MontageTrimInvalid("order requires unique media ids")
    elif field == "text":
        if item is not None and not isinstance(item, str):
            raise MontageTrimInvalid("caption must be text or null")
    elif field == "settings":
        allowed = {"logo_asset", "intro_asset", "intro_duration", "outro_asset", "outro_duration"}
        if not isinstance(item, dict) or set(item) - allowed:
            raise MontageTrimInvalid("invalid package branding fields")
        for name, setting in item.items():
            if setting is None:
                continue
            if name.endswith("_duration"):
                if isinstance(setting, bool) or not isinstance(setting, (int, float)) \
                        or not isfinite(setting) or setting < 1 / 25:
                    raise MontageTrimInvalid("branding duration must be finite and positive")
            elif not isinstance(setting, str) or "\\" in setting \
                    or Path(setting).is_absolute() or ".." in Path(setting).parts:
                raise MontageTrimInvalid("branding asset must be a relative artifact reference")


def merge_edit_groups(
    current: dict, changes: list[GroupEdit], *, photo_duration_seconds: float = 3.0,
) -> dict:
    """Three-way merge whole edit groups, preserving all untouched values."""
    result = deepcopy(current)
    media = {entry["media_id"]: entry for entry in current.get("media", [])}
    selections = manifest_selections(current)
    conflicts: list[dict] = []
    seen: set[str] = set()
    for change in changes:
        key = change.key
        if not isinstance(key, str) or key in seen:
            raise MontageTrimInvalid("edit group keys must be unique strings")
        seen.add(key)
        entry = None
        if key.startswith(("video:", "photo:")):
            mid = key.split(":", 1)[1]
            entry = media.get(mid)
            if entry is None or entry.get("status") != "finalized":
                conflicts.append({"key": key, "current": {"status": "unavailable"}})
                continue
            video = str(entry.get("content_type", "")).startswith("video/")
            if video != key.startswith("video:"):
                raise MontageTrimInvalid("edit group does not match media type")
            value = ({"ranges": selections.get(mid, [])} if video else
                     {"seconds": entry.get("photo_duration_seconds", photo_duration_seconds)})
        elif key == "order":
            value = {"ids": current.get("order", [])}
        elif key == "caption":
            value = {"text": current.get("caption")}
        elif key == "branding":
            value = {"settings": current.get("branding", {})}
        else:
            raise MontageTrimInvalid("unknown edit group")
        _validate_group_value(key, change.base, entry)
        _validate_group_value(key, change.proposed, entry)
        if change.proposed == value:
            continue
        if change.base != value:
            conflicts.append({"key": key, "current": deepcopy(value)})
            continue
        proposed = deepcopy(change.proposed)
        if key.startswith("video:"):
            mid = key.split(":", 1)[1]
            selected = result.setdefault("selections", deepcopy(selections))
            trims = result.setdefault("trims", {})
            if proposed["ranges"]:
                selected[mid] = validate_ranges(
                    proposed["ranges"], source_duration(entry or {}) or 0,
                )
                if len(selected[mid]) == 1:
                    trims[mid] = selected[mid][0]
                else:
                    trims.pop(mid, None)
            else:
                selected.pop(mid, None)
                trims.pop(mid, None)
        elif key.startswith("photo:"):
            assert entry is not None
            next(e for e in result["media"] if e["media_id"] == entry["media_id"])[
                "photo_duration_seconds"
            ] = proposed["seconds"]
        elif key == "order":
            finalized = {mid for mid, e in media.items() if e.get("status") == "finalized"}
            if set(proposed["ids"]) != finalized:
                raise MontageTrimInvalid("order must contain every finalized media id exactly once")
            result["order"] = proposed["ids"]
        elif key == "caption":
            result["caption"] = proposed["text"]
        elif key == "branding":
            result["branding"] = proposed["settings"]
    if conflicts:
        raise PackageEditConflict(conflicts)
    return result


def content_fields(document: dict) -> dict:
    return {key: document.get(key) for key in
            ("media", "order", "trims", "selections", "caption", "branding")}


def export_document(path: Path, document: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
