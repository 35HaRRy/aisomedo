from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from dojo.adapters.clock import SystemClock
from dojo.ports import Clock


class HmacSignedUrlStore:
    """Short-lived unguessable URLs scoped to the approved render only.

    Only ``render/reel.mp4`` beneath a package may be exposed; any other
    artifact path raises ``ValueError`` so raw package media is never
    publicly reachable. Tokens expire after ``ttl`` and are single-scope:
    one token maps to exactly one immutable artifact file.
    """

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        ttl_seconds: int = 3600,
        clock: Clock | None = None,
    ) -> None:
        if not secret:
            raise ValueError("signed URL secret is required")
        self._base_url = base_url.rstrip("/")
        self._secret = secret.encode("utf-8")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or SystemClock()
        self._records: dict[str, dict] = {}

    def _token(self, artifact: str, expires_at: datetime) -> str:
        msg = f"{artifact}|{expires_at.isoformat()}".encode("utf-8")
        digest = hmac.new(self._secret, msg, hashlib.sha256).hexdigest()
        return f"{digest[:32]}{secrets.token_hex(4)}"

    @staticmethod
    def _token_from_url(url: str) -> str:
        return url.rstrip("/").rsplit("/", 1)[-1]

    def create(self, artifact_path: Path) -> str:
        path = Path(artifact_path)
        if path.name != "reel.mp4" or path.parent.name != "render":
            raise ValueError("signed URLs are scoped to the approved render only")
        if not path.is_file():
            raise ValueError(f"artifact {path} does not exist")
        expires_at = self._clock.now() + self._ttl
        token = self._token(str(path), expires_at)
        self._records[token] = {
            "path": path,
            "expires_at": expires_at,
            "revoked": False,
        }
        return f"{self._base_url}/pub/{token}"

    def resolve(self, url_or_token: str) -> Path:
        token = self._token_from_url(url_or_token)
        record = self._records.get(token)
        if record is None or record["revoked"]:
            raise ValueError("signed URL is revoked or unknown")
        if self._clock.now() > record["expires_at"]:
            raise ValueError("signed URL expired")
        path = Path(record["path"])
        if path.name != "reel.mp4" or path.parent.name != "render":
            raise ValueError("signed URLs are scoped to the approved render only")
        if not path.is_file():
            raise ValueError("artifact no longer exists")
        return path

    def revoke(self, url: str) -> None:
        token = self._token_from_url(url)
        record = self._records.get(token)
        if record is not None:
            record["revoked"] = True
