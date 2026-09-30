"""Android client version policy (issue #24).

Supports the current and immediately previous Android release: the default
minimum is ``max(1, current - 1)``. An explicit ``ANDROID_MIN_VERSION_CODE``
may raise the floor (e.g. after a breaking change) but never lower it below
``current - 1`` silently — a floor below N-1 raises instead of widening
support unintentionally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class VersionPolicy:
    min_version_code: int
    current_version_code: int
    update_url: str


def _parse_version_code(raw: str, name: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"invalid {name} {raw!r}: must be an integer") from exc
    if value < 1:
        raise ValueError(f"invalid {name} {raw!r}: must be >= 1")
    return value


def resolve_version_policy() -> VersionPolicy:
    raw_current = os.environ.get("ANDROID_CURRENT_VERSION_CODE", "1")
    current = _parse_version_code(raw_current, "ANDROID_CURRENT_VERSION_CODE")
    default_min = max(1, current - 1)
    raw_min = os.environ.get("ANDROID_MIN_VERSION_CODE", "").strip()
    minimum = _parse_version_code(raw_min, "ANDROID_MIN_VERSION_CODE") if raw_min else default_min
    if minimum > current:
        raise ValueError(f"invalid ANDROID_MIN_VERSION_CODE {minimum}: above current {current}")
    if minimum < default_min:
        raise ValueError(
            f"invalid ANDROID_MIN_VERSION_CODE {minimum}: "
            f"below N-1 floor {default_min} for current {current}"
        )
    update_url = os.environ.get("ANDROID_UPDATE_URL", "").strip()
    if update_url:
        parsed = urlparse(update_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"invalid ANDROID_UPDATE_URL {update_url!r}: must be https://")
    return VersionPolicy(
        min_version_code=minimum, current_version_code=current, update_url=update_url
    )
