from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken

from dojo.exceptions import MetaTokenEncryptionError
from dojo.model import MetaCandidate


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
        return f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"

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
        graph_version: str = "v19.0",
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
