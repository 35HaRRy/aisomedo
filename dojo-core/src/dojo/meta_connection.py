from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from dojo.adapters.clock import SystemClock
from dojo.exceptions import (
    MetaAccountInvalid,
    MetaOAuthFailed,
    MetaOAuthStateInvalid,
    MetaProviderUnavailable,
    MetaReturnUriInvalid,
    MetaTokenEncryptionError,
    MetaTokenInvalid,
)
from dojo.model import (
    META_HEALTH_HEALTHY,
    META_HEALTH_NOT_CONNECTED,
    META_HEALTH_RECONNECT_REQUIRED,
    META_HEALTH_REFRESH_DUE,
    AuditEvent,
    MetaCandidate,
    MetaConnectionStatus,
    MetaOAuthAttempt,
)
from dojo.ports import InstagramTokenProvider

REFRESH_WINDOW = timedelta(days=7)
ATTEMPT_TTL = timedelta(minutes=10)
DAILY_CHECK_INTERVAL = timedelta(hours=24)


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _sanitize_error(msg: str) -> str:
    # strip tokens/codes/state — keep short sanitized message
    return msg[:200]


class DojoMetaConnection:
    def __init__(
        self,
        *,
        store: object,
        provider: object,
        cipher: object,
        audit: object | None = None,
        clock: object | None = None,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        graph_version: str = "v26.0",
        allowed_return_uris: list[str] | None = None,
        oauth_scope: str = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
        instagram_provider: InstagramTokenProvider | None = None,
    ) -> None:
        if not app_id or not app_secret or not redirect_uri:
            raise MetaTokenEncryptionError("meta OAuth config missing")
        # cipher validation: try encrypt/decrypt roundtrip if key provided
        try:
            enc = cipher.encrypt("test")  # type: ignore[attr-defined]
            dec = cipher.decrypt(enc)  # type: ignore[attr-defined]
            if dec != "test":
                raise MetaTokenEncryptionError("cipher roundtrip failed")
        except Exception as exc:
            raise MetaTokenEncryptionError(str(exc)) from exc
        self._store = store
        self._provider = provider
        self._cipher = cipher
        self._audit = audit
        self._clock = clock or SystemClock()
        self._app_id = app_id
        self._app_secret = app_secret
        self._redirect_uri = redirect_uri
        self._graph_version = graph_version
        self._allowed_return_uris = list(allowed_return_uris or [])
        self._oauth_scope = oauth_scope
        self._instagram_provider = instagram_provider

    def connect_instagram_token(self, client_id: int, token: str) -> MetaConnectionStatus:
        if (not token.strip() or not token.isascii() or len(token) > 16384 or any(c.isspace() for c in token.strip())):
            raise MetaTokenInvalid("A valid Instagram access token is required")
        if self._instagram_provider is None:
            raise MetaProviderUnavailable("Instagram Login is not configured")
        token = token.strip()
        candidate = self._instagram_provider.get_account(token)
        encrypted = self._cipher.encrypt(token)  # type: ignore[attr-defined]
        now = self._now()
        status = self._store.upsert_active(  # type: ignore[attr-defined]
            ig_user_id=candidate.ig_user_id, ig_username=candidate.ig_username,
            page_id=None, page_name=None, encrypted_token=encrypted,
            token_expires_at=None, health=META_HEALTH_HEALTHY,
            last_checked_at=now, last_refreshed_at=None, last_error=None,
            connection_type="instagram_login",
        )
        if self._audit is not None:
            try:
                self._audit.append(AuditEvent(  # type: ignore[attr-defined]
                    action="meta.connected", actor=str(client_id), occurred_at=now,
                    details={
                        "ig_user_id": candidate.ig_user_id, "connection_type": "instagram_login",
                    },
                ))
            except Exception:
                pass
        return status

    def _now(self) -> datetime:
        n = self._clock.now()  # type: ignore[attr-defined]
        if n.tzinfo is None:
            n = n.replace(tzinfo=UTC)
        return n

    def _validate_return_uri(self, return_uri: str | None) -> None:
        if return_uri is None:
            return
        if return_uri not in self._allowed_return_uris:
            # also allow prefix match for deep links with query? strict equality per design
            raise MetaReturnUriInvalid(f"return_uri not allowlisted: {return_uri}")

    def start(self, client_id: int, return_uri: str | None = None) -> tuple[str, str]:
        self._validate_return_uri(return_uri)
        now = self._now()
        raw_state = secrets.token_urlsafe(32)
        state_hash = _hash_state(raw_state)
        attempt_id = str(uuid.uuid4())
        # store pending attempt
        attempt = {
            "id": attempt_id,
            "state_hash": state_hash,
            "initiated_by_client_id": client_id,
            "return_uri": return_uri,
            "status": "pending",
            "created_at": now,
            "expires_at": now + ATTEMPT_TTL,
            "candidates": None,
            "encrypted_temp_token": None,
            "temp_token_expires_at": None,
            "last_error": None,
            "raw_state": raw_state,  # stored only for retrieval via state_hash lookup; not persisted in DB raw
        }
        # DB store will hold hash; we keep raw only in memory attempt? For DB we store hash
        self._store.create_attempt(attempt)  # type: ignore[attr-defined]
        auth_url = self._provider.build_auth_url(raw_state, self._redirect_uri)  # type: ignore[attr-defined]
        # For convenience, return both url and attempt_id (attempt_id is not in URL, callback will resolve via state)
        return auth_url, attempt_id

    def complete_callback(self, state: str, code: str) -> str:
        now = self._now()
        state_hash = _hash_state(state)
        rec = self._store.find_attempt_by_state_hash(state_hash)  # type: ignore[attr-defined]
        if rec is None:
            raise MetaOAuthStateInvalid("invalid state")
        if rec["status"] != "pending":
            raise MetaOAuthStateInvalid("state already consumed")
        if rec["expires_at"] < now:
            self._store.mark_attempt_failed(rec["id"], "expired")  # type: ignore[attr-defined]
            raise MetaOAuthStateInvalid("state expired")
        # consume attempt (single-use)
        # mark as processing; we will complete or fail
        try:
            short_token, short_exp = self._provider.exchange_code(code, self._redirect_uri)  # type: ignore[attr-defined]
            long_token, long_exp = self._provider.exchange_long_lived(short_token)  # type: ignore[attr-defined]
            candidates = self._provider.list_eligible_accounts(long_token)  # type: ignore[attr-defined]
            if not candidates:
                raise MetaOAuthFailed("no eligible Instagram Professional accounts")
            enc = self._cipher.encrypt(long_token)  # type: ignore[attr-defined]
            # store candidates + temp token
            self._store.mark_attempt_completed(rec["id"], candidates, enc, long_exp)  # type: ignore[attr-defined]
            return rec["id"]
        except MetaOAuthFailed:
            raise
        except MetaOAuthStateInvalid:
            raise
        except Exception as exc:
            sanitized = _sanitize_error(str(exc))
            try:
                self._store.mark_attempt_failed(rec["id"], sanitized)  # type: ignore[attr-defined]
            except Exception:
                pass
            raise MetaOAuthFailed(sanitized) from exc

    def get_attempt(self, client_id: int, attempt_id: str) -> MetaOAuthAttempt:
        now = self._now()
        rec = self._store.get_meta_attempt(attempt_id)  # type: ignore[attr-defined]
        if rec is None:
            raise MetaOAuthStateInvalid("attempt not found")
        if rec["initiated_by_client_id"] != client_id:
            raise MetaOAuthStateInvalid("attempt belongs to different client")
        if rec["expires_at"] < now and rec["status"] == "pending":
            self._store.mark_attempt_failed(attempt_id, "expired")  # type: ignore[attr-defined]
            rec = self._store.get_meta_attempt(attempt_id)  # type: ignore[attr-defined]
        # map to model
        cands = []
        for c in rec.get("candidates") or []:
            if isinstance(c, dict):
                cands.append(MetaCandidate(**c))
            else:
                cands.append(c)
        return MetaOAuthAttempt(
            id=rec["id"],
            status=rec["status"],
            candidates=cands,
            created_at=rec["created_at"],
            expires_at=rec["expires_at"],
        )

    def select_account(self, client_id: int, attempt_id: str, ig_user_id: str) -> MetaConnectionStatus:
        now = self._now()
        rec = self._store.get_meta_attempt(attempt_id)  # type: ignore[attr-defined]
        if rec is None:
            raise MetaOAuthStateInvalid("attempt not found")
        if rec["initiated_by_client_id"] != client_id:
            raise MetaOAuthStateInvalid("attempt belongs to different client")
        if rec["status"] != "completed":
            raise MetaOAuthStateInvalid(f"attempt not completed: {rec['status']}")
        if rec["expires_at"] < now:
            raise MetaOAuthStateInvalid("attempt expired")
        cands = rec.get("candidates") or []
        # normalize candidates to dicts
        chosen = None
        for c in cands:
            cid = c["ig_user_id"] if isinstance(c, dict) else c.ig_user_id  # type: ignore[union-attr]
            if cid == ig_user_id:
                chosen = c
                break
        if chosen is None:
            raise MetaAccountInvalid(f"ig_user_id not eligible: {ig_user_id}")
        if isinstance(chosen, dict):
            cand = MetaCandidate(**chosen)
        else:
            cand = chosen  # type: ignore[assignment]
        enc_token = rec.get("encrypted_temp_token")
        exp = rec.get("temp_token_expires_at")
        if not enc_token or not exp:
            raise MetaOAuthFailed("attempt missing token")
        # validate token still valid via provider inspect
        try:
            plain = self._cipher.decrypt(enc_token)  # type: ignore[attr-defined]
            valid, _ = self._provider.inspect_token(plain)  # type: ignore[attr-defined]
            if not valid:
                raise MetaOAuthFailed("token no longer valid")
        except MetaAccountInvalid:
            raise
        except Exception as exc:
            raise MetaOAuthFailed(_sanitize_error(str(exc))) from exc
        # atomic upsert active
        status = self._store.upsert_active(  # type: ignore[attr-defined]
            ig_user_id=cand.ig_user_id,
            ig_username=cand.ig_username,
            page_id=cand.page_id,
            page_name=cand.page_name,
            encrypted_token=enc_token,
            token_expires_at=exp,
            health=META_HEALTH_HEALTHY,
            last_checked_at=now,
            last_refreshed_at=None,
            last_error=None,
        )
        # consume attempt
        self._store.consume_attempt(attempt_id)  # type: ignore[attr-defined]
        if self._audit is not None:
            try:
                self._audit.append(AuditEvent(action="meta.connected", actor=str(client_id), occurred_at=now, details={"ig_user_id": cand.ig_user_id}))  # type: ignore[attr-defined]
            except Exception:
                pass
        return status

    def get_status(self) -> MetaConnectionStatus:
        now = self._now()
        rec = self._store.get_meta_status()  # type: ignore[attr-defined]
        if rec is None:
            return MetaConnectionStatus(health=META_HEALTH_NOT_CONNECTED)
        # derive refresh_due
        health = rec.health
        expires_at = rec.expires_at
        # if reconnect_required already, keep it
        if health != META_HEALTH_RECONNECT_REQUIRED and expires_at is not None:
            if expires_at - now <= REFRESH_WINDOW:
                # if not already reconnect_required, mark as refresh_due for display
                if health == META_HEALTH_HEALTHY:
                    health = META_HEALTH_REFRESH_DUE
        return MetaConnectionStatus(
            health=health,
            ig_user_id=rec.ig_user_id,
            ig_username=rec.ig_username,
            page_id=rec.page_id,
            page_name=rec.page_name,
            expires_at=expires_at,
            last_checked_at=rec.last_checked_at,
            last_refreshed_at=rec.last_refreshed_at,
            last_error=rec.last_error,
            connection_type=rec.connection_type,
        )

    def get_valid_token(self) -> str | None:
        snapshot = self._store.get_active_snapshot()  # type: ignore[attr-defined]
        if snapshot is None:
            return None
        rec, encrypted = snapshot
        if rec.health == META_HEALTH_RECONNECT_REQUIRED:
            return None
        if rec.expires_at is not None and rec.expires_at <= self._now():
            return None
        try:
            return self._cipher.decrypt(encrypted)  # type: ignore[attr-defined]
        except Exception:
            return None

    def maintain(self) -> MetaConnectionStatus:
        now = self._now()
        snapshot = self._store.get_active_snapshot()  # type: ignore[attr-defined]
        if snapshot is None:
            return MetaConnectionStatus(health=META_HEALTH_NOT_CONNECTED)
        rec, encrypted = snapshot
        if rec.health == META_HEALTH_RECONNECT_REQUIRED:
            return self.get_status()
        if rec.connection_type == "instagram_login":
            return self._maintain_instagram(rec, now, encrypted)
        last_checked = rec.last_checked_at
        needs_refresh = rec.expires_at is not None and (rec.expires_at - now <= REFRESH_WINDOW)
        should_check = (
            last_checked is None or now - last_checked >= DAILY_CHECK_INTERVAL or needs_refresh
        )
        if not should_check:
            return self.get_status()
        try:
            plain = self._cipher.decrypt(encrypted)  # type: ignore[attr-defined]
            if needs_refresh:
                token, expiry = self._provider.refresh_token(plain)  # type: ignore[attr-defined]
                refreshed = self._cipher.encrypt(token)  # type: ignore[attr-defined]
                updated = self._store.update_token(  # type: ignore[attr-defined]
                    refreshed, expiry, now, expected_encrypted_token=encrypted
                )
                if updated is None:
                    return self.get_status()
                encrypted = refreshed
            else:
                valid, _ = self._provider.inspect_token(plain)  # type: ignore[attr-defined]
                if not valid:
                    raise MetaTokenInvalid("token invalid")
            self._store.update_health(  # type: ignore[attr-defined]
                META_HEALTH_HEALTHY, now, None, expected_encrypted_token=encrypted
            )
        except Exception as exc:
            msg = _sanitize_error(str(exc))
            transient = any(word in msg.lower() for word in ("transient", "timeout", "network"))
            health = rec.health if transient else META_HEALTH_RECONNECT_REQUIRED
            updated = self._store.update_health(  # type: ignore[attr-defined]
                health, now, msg, expected_encrypted_token=encrypted
            )
            if updated is not None and needs_refresh and not transient and self._audit is not None:
                try:
                    self._audit.append(AuditEvent(  # type: ignore[attr-defined]
                        action="meta.refresh_failed", actor="worker", occurred_at=now,
                        details={"error": msg},
                    ))
                except Exception:
                    pass
        return self.get_status()

    def _maintain_instagram(
        self, rec: MetaConnectionStatus, now: datetime, encrypted: str
    ) -> MetaConnectionStatus:
        if rec.expires_at is not None and rec.expires_at <= now:
            self._store.update_health(  # type: ignore[attr-defined]
                META_HEALTH_RECONNECT_REQUIRED, now, "Instagram token expired",
                expected_encrypted_token=encrypted,
            )
            return self.get_status()
        if rec.last_checked_at is not None and now - rec.last_checked_at < DAILY_CHECK_INTERVAL:
            return self.get_status()
        try:
            if self._instagram_provider is None:
                raise MetaProviderUnavailable("Instagram Login is not configured")
            plain = self._cipher.decrypt(encrypted)  # type: ignore[attr-defined]
            account = self._instagram_provider.get_account(plain)
            if account.ig_user_id != rec.ig_user_id:
                raise MetaTokenInvalid("Instagram account changed; reconnect required")
            due = rec.expires_at is None or rec.expires_at - now <= REFRESH_WINDOW
            if due:
                token, expiry = self._instagram_provider.refresh_token(plain)
                refreshed = self._cipher.encrypt(token)  # type: ignore[attr-defined]
                updated = self._store.update_token(  # type: ignore[attr-defined]
                    refreshed, expiry, now, expected_encrypted_token=encrypted
                )
                if updated is None:
                    return self.get_status()
                encrypted = refreshed
            self._store.update_health(  # type: ignore[attr-defined]
                META_HEALTH_HEALTHY, now, None, expected_encrypted_token=encrypted
            )
        except (MetaTokenInvalid, MetaTokenEncryptionError):
            self._store.update_health(  # type: ignore[attr-defined]
                META_HEALTH_RECONNECT_REQUIRED, now,
                "Instagram token or permissions invalid; reconnect",
                expected_encrypted_token=encrypted,
            )
        except MetaProviderUnavailable:
            self._store.update_health(  # type: ignore[attr-defined]
                rec.health, now, "Instagram temporarily unavailable; retry on next daily check",
                expected_encrypted_token=encrypted,
            )
        return self.get_status()
