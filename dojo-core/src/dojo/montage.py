from __future__ import annotations

from math import isfinite

from dojo.exceptions import MontageTrimInvalid
from dojo.model import VideoRange, VideoSelections

REEL_FPS = 25


def manifest_selections(manifest: dict) -> VideoSelections:
    """Normalize legacy retained windows without rewriting their manifest."""
    if "selections" in manifest:
        return {mid: [{"start": r["start"], "end": r["end"]} for r in ranges]
                for mid, ranges in manifest["selections"].items()}
    return {mid: [{"start": trim["start"], "end": trim["end"]}]
            for mid, trim in manifest.get("trims", {}).items()}


def source_duration(entry: dict) -> float | None:
    value = entry.get("processed", {}).get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) and value > 0 else None


def validate_ranges(ranges: list[VideoRange], duration: float) -> list[VideoRange]:
    if not isfinite(duration) or duration <= 0:
        raise MontageTrimInvalid("video source duration is unavailable")
    if not isinstance(ranges, list) or not ranges:
        raise MontageTrimInvalid("select at least one range, or omit the video for full playback")
    cleaned: list[VideoRange] = []
    for item in ranges:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise MontageTrimInvalid("range requires start and end")
        start, end = item["start"], item["end"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
               for v in (start, end)):
            raise MontageTrimInvalid("range endpoints must be finite numbers")
        if not 0 <= start < end <= duration or end - start + 1e-9 < 1 / REEL_FPS:
            raise MontageTrimInvalid("range must be within the source and at least one frame long")
        cleaned.append({"start": float(start), "end": float(end)})
    cleaned.sort(key=lambda r: r["start"])
    if any(left["end"] > right["start"] for left, right in zip(cleaned, cleaned[1:])):
        raise MontageTrimInvalid("ranges must not overlap or duplicate")
    return cleaned


def effective_duration(entry: dict, ranges: list[VideoRange] | None, photo_seconds: float) -> float:
    if not str(entry.get("content_type", "")).startswith("video/"):
        return float(entry.get("photo_duration_seconds", photo_seconds))
    duration = source_duration(entry)
    if duration is None:
        return 0.0
    if ranges is None:
        return duration
    return sum(r["end"] - r["start"] for r in validate_ranges(ranges, duration))
