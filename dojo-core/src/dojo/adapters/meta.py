from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from dojo.adapters.clock import SystemClock
from dojo.exceptions import MetaProviderUnavailable, MetaTokenEncryptionError, MetaTokenInvalid
from dojo.model import MetaCandidate
from dojo.ports import Clock


logger = logging.getLogger(__name__)


class FernetCipher:
    def __init__(self, key: str) -> None:
        # key must be 32-byte base64url Fernet key
        try:
            # validate by constructing Fernet
            Fernet(key.encode() if isinstance(key, str) else key)
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as exc:
            raise MetaTokenEncryptionError(f"invalid encryption key: {exc}") from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise MetaTokenEncryptionError("decryption failed") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("utf-8")


class StubMetaOAuthProvider:
    def __init__(
        self,
        *,
        candidates: list[MetaCandidate] | None = None,
        refresh_result: tuple[str, datetime] | None = None,
        inspect_valid: bool = True,
    ) -> None:
        self._candidates = candidates or [
            MetaCandidate(ig_user_id="ig_123", ig_username="dojo_test", page_id="page_1", page_name="Dojo Page")
        ]
        self._refresh_result = refresh_result
        self._inspect_valid = inspect_valid
        self.calls: list[str] = []

    def build_auth_url(self, state: str, redirect_uri: str) -> str:
        self.calls.append("build_auth_url")
        params = {
            "client_id": "test_app",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "instagram_basic,instagram_content_publish",
            "response_type": "code",
        }
        return f"https://www.facebook.com/v26.0/dialog/oauth?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> tuple[str, datetime]:
        self.calls.append("exchange_code")
        if code == "bad_code":
            raise RuntimeError("provider rejected code")
        return "short_token_abc", datetime.now(UTC) + timedelta(hours=1)

    def exchange_long_lived(self, short_token: str) -> tuple[str, datetime]:
        self.calls.append("exchange_long_lived")
        return "long_token_xyz", datetime.now(UTC) + timedelta(days=60)

    def list_eligible_accounts(self, long_token: str) -> list[MetaCandidate]:
        self.calls.append("list_eligible_accounts")
        if long_token == "no_accounts":
            return []
        return list(self._candidates)

    def refresh_token(self, long_token: str) -> tuple[str, datetime]:
        self.calls.append("refresh_token")
        if "transient" in long_token:
            raise RuntimeError("transient network error")
        if long_token == "bad_refresh":
            raise RuntimeError("refresh failed definitive")
        if self._refresh_result:
            return self._refresh_result
        return "refreshed_token", datetime.now(UTC) + timedelta(days=60)

    def inspect_token(self, token: str) -> tuple[bool, datetime | None]:
        self.calls.append("inspect_token")
        if token == "invalid_token":
            return False, None
        if "transient" in token:
            raise RuntimeError("transient network error")
        return self._inspect_valid, datetime.now(UTC) + timedelta(days=60)


class HttpMetaOAuthProvider:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        graph_version: str = "v26.0",
        http_client: object | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._redirect_uri = redirect_uri
        self._graph_version = graph_version
        self._http = http_client

    def build_auth_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
            "response_type": "code",
        }
        return f"https://www.facebook.com/{self._graph_version}/dialog/oauth?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> tuple[str, datetime]:
        # Real implementation would call Graph API; stubbed for now to avoid network in tests
        raise NotImplementedError("HttpMetaOAuthProvider requires live Meta credentials")

    def exchange_long_lived(self, short_token: str) -> tuple[str, datetime]:
        raise NotImplementedError

    def list_eligible_accounts(self, long_token: str) -> list[MetaCandidate]:
        raise NotImplementedError

    def refresh_token(self, long_token: str) -> tuple[str, datetime]:
        raise NotImplementedError

    def inspect_token(self, token: str) -> tuple[bool, datetime | None]:
        raise NotImplementedError


class HttpMetaPublisher:
    """Publish Reels through the official Instagram Graph API.

    Flow: create REELS container from the signed video URL, poll the
    container ``status_code`` until ``FINISHED``, then ``media_publish``
    the saved container id. Timeouts and 5xx/transient errors raise
    ``MetaPublishUncertain`` (retain ``-publishing``, poll, never mint a
    fresh container on reconcile); definitive 4xx/API errors raise
    ``MetaPublishFailed`` (restore to active for retry).
    """

    _TRANSIENT_CODES = {1, 2, 4, 17, 32, 613}

    def __init__(
        self,
        *,
        connection_store: object,
        cipher: object,
        graph_version: str = "v26.0",
        host: str = "https://graph.facebook.com",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._store = connection_store
        self._cipher = cipher
        self._graph_version = graph_version
        self._host = host.rstrip("/")
        self._http = http_client

    def _client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(timeout=30.0)

    def _credentials(self) -> tuple[str, str]:
        from dojo.exceptions import MetaNotConnected

        snapshot = self._store.get_active_snapshot()  # type: ignore[attr-defined]
        if snapshot is None:
            raise MetaNotConnected("no Instagram account connected")
        status, encrypted = snapshot
        token = self._cipher.decrypt(encrypted)  # type: ignore[attr-defined]
        if not status.ig_user_id:
            from dojo.exceptions import MetaPublishFailed as Failed

            raise Failed("connected account has no Instagram user id")
        return token, status.ig_user_id

    @staticmethod
    def _error_kind(data: dict) -> str | None:
        error = data.get("error")
        if not isinstance(error, dict):
            return None
        if error.get("is_transient") or error.get("code") in HttpMetaPublisher._TRANSIENT_CODES:
            return "transient"
        return "definitive"

    def _post(self, path: str, payload: dict) -> dict:
        from dojo.exceptions import MetaPublishFailed as Failed
        from dojo.exceptions import MetaPublishUncertain as Uncertain

        url = f"{self._host}/{self._graph_version}/{path.lstrip('/')}"
        close = self._http is None
        client = self._client()
        try:
            response = client.post(url, data=payload)
        except httpx.RequestError:
            raise Uncertain("Meta request timed out; outcome unknown") from None
        finally:
            if close:
                client.close()
        if response.status_code == 429 or response.status_code >= 500:
            raise Uncertain(f"Meta temporarily unavailable ({response.status_code})")
        try:
            data = response.json()
        except ValueError:
            raise Uncertain("invalid Meta response; outcome unknown") from None
        if not isinstance(data, dict):
            raise Uncertain("invalid Meta response; outcome unknown")
        kind = self._error_kind(data)
        if kind == "transient":
            raise Uncertain(f"Meta transient error: {data.get('error')}")
        if kind == "definitive" or response.status_code in (400, 401, 403):
            raise Failed(f"Meta rejected request: {data.get('error')}")
        if not response.is_success:
            raise Uncertain(f"Meta request failed ({response.status_code}); outcome unknown")
        return data

    def _get(self, path: str, params: dict) -> dict:
        from dojo.exceptions import MetaPublishFailed as Failed
        from dojo.exceptions import MetaPublishUncertain as Uncertain

        url = f"{self._host}/{self._graph_version}/{path.lstrip('/')}"
        close = self._http is None
        client = self._client()
        try:
            response = client.get(url, params=params)
        except httpx.RequestError:
            raise Uncertain("Meta status check timed out; outcome unknown") from None
        finally:
            if close:
                client.close()
        if response.status_code == 429 or response.status_code >= 500:
            raise Uncertain(f"Meta temporarily unavailable ({response.status_code})")
        try:
            data = response.json()
        except ValueError:
            raise Uncertain("invalid Meta response; outcome unknown") from None
        if not isinstance(data, dict):
            raise Uncertain("invalid Meta response; outcome unknown")
        kind = self._error_kind(data)
        if kind == "transient":
            raise Uncertain(f"Meta transient error: {data.get('error')}")
        if kind == "definitive" or response.status_code in (400, 401, 403):
            raise Failed(f"Meta rejected request: {data.get('error')}")
        if not response.is_success:
            raise Uncertain(f"Meta request failed ({response.status_code}); outcome unknown")
        return data

    def publish_reel(self, signed_url: str, caption: str) -> None:
        container_id = self.create_container(signed_url, caption)
        status = self.get_container_status(container_id)
        if status != "FINISHED":
            from dojo.exceptions import MetaPublishUncertain as Uncertain

            raise Uncertain(f"container {container_id} reported {status}")
        self.publish_container(container_id)

    def create_container(self, signed_url: str, caption: str) -> str:
        from dojo.exceptions import MetaPublishFailed as Failed

        token, ig_user_id = self._credentials()
        data = self._post(
            f"{ig_user_id}/media",
            {
                "media_type": "REELS",
                "video_url": signed_url,
                "caption": caption,
                "access_token": token,
            },
        )
        container_id = data.get("id")
        if not isinstance(container_id, str) or not container_id:
            raise Failed("Meta did not return a container id")
        return container_id

    def get_container_status(self, container_id: str) -> str:
        from dojo.exceptions import MetaPublishFailed as Failed

        token, _ = self._credentials()
        data = self._get(f"{container_id}", {"fields": "status_code", "access_token": token})
        status = data.get("status_code")
        if not isinstance(status, str) or not status:
            raise Failed(f"Meta returned no status for container {container_id}")
        return status

    def publish_container(self, container_id: str) -> str:
        from dojo.exceptions import MetaPublishFailed as Failed

        token, ig_user_id = self._credentials()
        data = self._post(
            f"{ig_user_id}/media_publish",
            {"creation_id": container_id, "access_token": token},
        )
        media_id = data.get("id")
        if not isinstance(media_id, str) or not media_id:
            raise Failed("Meta did not return a media id")
        return media_id


class HttpInstagramTokenProvider:
    """Instagram Login tokens; never use Facebook's token or account endpoints."""

    def __init__(
        self,
        *,
        graph_version: str = "v26.0",
        http_client: httpx.Client | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._graph_version = graph_version
        self._http = http_client
        self._clock = clock or SystemClock()

    def _get(self, path: str, token: str, params: dict[str, str] | None = None) -> dict:
        url = f"https://graph.instagram.com/{path}"
        merged = {**(params or {}), "access_token": token}
        logger.warning("Instagram request path: path=%s params=%s", path, merged)
        try:
            if self._http is None:
                with httpx.Client(timeout=20, follow_redirects=False) as client:
                    response = client.get(url, params=merged)
            else:
                response = self._http.get(
                    url, params=merged,
                    timeout=20, follow_redirects=False,
                )

        except httpx.RequestError:
            raise MetaProviderUnavailable("Instagram temporarily unavailable") from None
        if response.status_code == 429 or response.status_code >= 500:
            raise MetaProviderUnavailable("Instagram temporarily unavailable")
        try:
            data = response.json()
        except ValueError:
            raise MetaProviderUnavailable("Invalid Instagram response") from None
        if not isinstance(data, dict):
            raise MetaProviderUnavailable("Invalid Instagram response")
        error = data.get("error")
        if isinstance(error, dict):
            if error.get("is_transient") or error.get("code") in (1, 2, 4, 17, 32, 613):
                raise MetaProviderUnavailable("Instagram temporarily unavailable")
            if error.get("code") in (10, 100, 190, 200):
                raise MetaTokenInvalid("Instagram token is invalid or lacks required permissions")
            raise MetaProviderUnavailable("Instagram request failed")
        if response.status_code in (400, 401, 403):
            raise MetaTokenInvalid("Instagram token is invalid or lacks required permissions")
        if not response.is_success:
            raise MetaProviderUnavailable("Instagram request failed")
        return data

    def get_account(self, token: str) -> MetaCandidate:
        data = self._get(f"{self._graph_version}/me", token, {"fields": "user_id,username"})
        # Meta examples include both a direct object and a single-entry data envelope.
        if isinstance(data.get("data"), list) and len(data["data"]) == 1:
            data = data["data"][0]
        if not isinstance(data, dict):
            raise MetaProviderUnavailable("Invalid Instagram account response")
        user_id, username = data.get("user_id"), data.get("username")
        if not isinstance(user_id, (str, int)) or not str(user_id).isdigit():
            raise MetaProviderUnavailable("Instagram account ID missing")
        if not isinstance(username, str) or not username.strip():
            raise MetaProviderUnavailable("Instagram username missing")
        # NOTE: graph.instagram.com has no /me/permissions edge (that is a
        # graph.facebook.com endpoint). Querying it returns code 100
        # "Unsupported get request. Object with ID 'permissions' does not exist".
        # Scopes are returned once at OAuth code exchange time; at runtime a
        # successful /me plus downstream 190/200 handling is the signal.
        # Missing publish scope surfaces at publish time as MetaTokenInvalid.
        return MetaCandidate(str(user_id), username, None, None)

    def refresh_token(self, token: str) -> tuple[str, datetime]:
        started_at = self._clock.now()
        data = self._get("refresh_access_token", token, {"grant_type": "ig_refresh_token"})
        refreshed, expires_in = data.get("access_token"), data.get("expires_in")
        if not isinstance(refreshed, str) or not refreshed:
            raise MetaProviderUnavailable("Invalid Instagram refresh response")
        if type(expires_in) is not int or not 0 < expires_in <= 60 * 24 * 3600:
            raise MetaProviderUnavailable("Invalid Instagram token expiry")
        return refreshed, started_at + timedelta(seconds=expires_in)
