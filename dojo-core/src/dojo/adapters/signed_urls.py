from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from dojo.adapters.clock import SystemClock
from dojo.organizations import organization_media_root
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
        media_root: Path | None = None,
        organization_id: int | None = None,
    ) -> None:
        if not secret:
            raise ValueError("signed URL secret is required")
        self._base_url = base_url.rstrip("/")
        self._secret = secret.encode("utf-8")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or SystemClock()
        self._records: dict[str, dict] = {}
        self._media_root = Path(media_root).resolve() if media_root is not None else None
        self._organization_id = organization_id

    def _token(self, artifact: str, expires_at: datetime) -> str:
        msg = f"{artifact}|{expires_at.isoformat()}".encode()
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
        if self._media_root is not None and self._organization_id is not None:
            workspace = organization_media_root(self._media_root, self._organization_id)
            relative = path.resolve().relative_to(workspace.resolve())
            if relative.parts[0] == "organizations":
                raise ValueError("artifact belongs to another organization")
            payload = base64.urlsafe_b64encode(json.dumps({
                "o": self._organization_id, "f": relative.as_posix(),
                "e": expires_at.timestamp(), "n": secrets.token_hex(8),
            }, separators=(",", ":")).encode()).decode().rstrip("=")
            signature = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
            token = f"v2.{payload}.{signature}"
        else:
            token = self._token(str(path), expires_at)
        self._records[token] = {
            "path": path,
            "expires_at": expires_at,
            "revoked": False,
        }
        return f"{self._base_url}/pub/{token}"

    def resolve(self, url_or_token: str) -> Path:
        token = self._token_from_url(url_or_token)
        if token.startswith("v2."):
            organization_id, relative = self._verified_token(token)
            if self._media_root is None:
                raise ValueError("signed URL media root is not configured")
            workspace = organization_media_root(self._media_root, organization_id).resolve()
            path = (workspace / relative).resolve()
            if (not path.is_relative_to(workspace) or Path(relative).parts[0] == "organizations"
                    or path.name != "reel.mp4" or path.parent.name != "render"
                    or not path.is_file()):
                raise ValueError("signed artifact is unavailable")
            return path
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

    def _verified_token(self, token: str) -> tuple[int, str]:
        if len(token) > 2048:
            raise ValueError("invalid signed URL")
        try:
            version, payload, signature = token.split(".")
            expected = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
            if version != "v2" or not hmac.compare_digest(signature, expected):
                raise ValueError("invalid signed URL")
            record = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            organization_id, relative = record["o"], record["f"]
            if (type(organization_id) is not int or organization_id <= 0
                    or not isinstance(relative, str) or not relative
                    or self._clock.now().timestamp() > record["e"]
                    or self._records.get(token, {}).get("revoked")
                    or (self._media_root is not None and self._revocation_path(token).exists())
                    or (self._organization_id is not None
                        and self._organization_id != organization_id)):
                raise ValueError("signed URL is expired, revoked, or outside this organization")
            return organization_id, relative
        except (KeyError, TypeError, UnicodeError) as exc:
            raise ValueError("invalid signed URL") from exc

    def token_owner(self, url_or_token: str) -> int | None:
        token = self._token_from_url(url_or_token)
        return self._verified_token(token)[0] if token.startswith("v2.") else None

    def _revocation_path(self, token: str) -> Path:
        assert self._media_root is not None
        digest = hashlib.sha256(token.encode()).hexdigest()
        return self._media_root / ".signed-url-revocations" / digest

    def revoke(self, url: str) -> None:
        token = self._token_from_url(url)
        if token.startswith("v2.") and self._media_root is not None:
            try:
                self._verified_token(token)
            except ValueError:
                return  # Expired or already-revoked tokens cannot be fetched anyway.
            marker = self._revocation_path(token)
            marker.parent.mkdir(parents=True, exist_ok=True)
            # shortcut: retain tiny revocation markers; prune after maximum TTL if volume grows.
            marker.touch()
        record = self._records.get(token)
        if record is not None:
            record["revoked"] = True
