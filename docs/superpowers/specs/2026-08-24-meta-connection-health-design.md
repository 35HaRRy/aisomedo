# Meta Connection and Connection Health — Design

Date: 2026-08-24
Source: Issue #17 (part of #1, Dojo Reel Publishing MVP), blocked by #3 (done).

## Problem

Publishing requires one Instagram Professional account (linked to a Facebook Page) authorized through browser-based Meta OAuth. Long-lived authorization must be stored encrypted on the backend, exposed to clients only as connection status (account name + health). Authorization must refresh before expiry; failed refresh blocks publication while preserving the active package and schedule state and requires reconnect. Reconnect must work without losing the active package.

## Decisions

1. **Dedicated deep module `DojoMetaConnection`.** New facade `dojo/meta_connection.py` alongside `DojoPublishing`/`DojoPairing`/`DojoSetup`. Keeps OAuth state, candidate discovery, encrypted credential lifecycle, status, atomic reconnect, and maintenance behind one small interface. `DojoPublishing` later consumes connection health for #18; FastAPI and the worker stay thin.
2. **Explicit account picker.** Meta may return multiple eligible Page-linked Professional accounts. The backend discovers candidates after the OAuth callback and the paired browser chooses one before any token becomes active. No implicit first-account selection.
3. **Authenticated encryption via required environment key.** `META_TOKEN_ENCRYPTION_KEY` (Fernet, 32-byte base64url) encrypts long-lived tokens at rest. No fallback or plaintext storage. Missing/invalid key fails construction.
4. **Hashed, single-use, client-bound OAuth state.** Random `state` is hashed at rest (`SHA-256`), bound to the initiating client, 10-minute TTL, single-use. Callback authenticates via valid unused state; attempt selection still requires the same paired client, preventing cross-client hijack.
5. **Allowlisted return URI.** `POST /api/meta/oauth/start` accepts an optional `return_uri`; only URIs in `META_ALLOWED_RETURN_URIS` (configured web origin + Android deep-link) are accepted. Callback redirects with opaque `attempt_id` or returns JSON when no allowlisted URI was supplied. Prevents open redirect.
6. **Atomic reconnect.** A new OAuth attempt never clears the active connection. Only successful `select_account` atomically replaces the singleton active row and scrubs temporary credentials. Abandoning or failing a reconnect leaves prior connection/health intact.
7. **Single active connection.** `meta_connections` holds at most one active row (singleton PK=1). No multi-account support. Disconnect is reconnect-only in #17.
8. **Maintenance via `maintain()`.** Worker calls `meta.maintain()` before any publication-capable work. Inside one idempotent tick: remote token/account validation at most once per 24h, refresh starting 7 days before `expires_at`, and health transitions. Transient network/provider outage keeps prior credential, records sanitized `last_error`, reports degraded check metadata, but does not revoke. Definitive invalid/revoked/refresh failure sets `reconnect_required` and audits sanitized reason. Package/schedule/review state is never mutated here.
9. **Setup checklist integration.** `DojoSetup.checklist()` gains an Instagram item, complete only while health is `healthy` or `refresh_due`; `not_connected` and `reconnect_required` remain incomplete.

## Domain Model (`dojo/model.py`)

```python
@dataclass(frozen=True)
class MetaConnectionStatus:
    health: str  # not_connected | healthy | refresh_due | reconnect_required
    ig_user_id: str | None = None
    ig_username: str | None = None
    page_id: str | None = None
    page_name: str | None = None
    expires_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_error: str | None = None  # sanitized, no token/code/state

@dataclass(frozen=True)
class MetaOAuthAttempt:
    id: str  # UUID
    status: str  # pending | completed | failed | expired
    candidates: list[MetaCandidate]  # safe display fields only
    created_at: datetime
    expires_at: datetime

@dataclass(frozen=True)
class MetaCandidate:
    ig_user_id: str
    ig_username: str
    page_id: str
    page_name: str
```

Health semantics:
- `healthy` — valid credential, expiry >7d, last daily check passed.
- `refresh_due` — expiry within 7d but credential still usable; next `maintain()` will refresh.
- `reconnect_required` — refresh or validation definitively failed; publication must be blocked until reconnect.
- `not_connected` — no active row.

## Exceptions (`dojo/exceptions.py`)

- `MetaConnectionError(DojoError)` base
- `MetaOAuthStateInvalid(MetaConnectionError)` — unknown/expired/reused/mismatched state
- `MetaOAuthFailed(MetaConnectionError)` — provider rejection during code exchange/discovery
- `MetaAccountInvalid(MetaConnectionError)` — unknown/ineligible account selection
- `MetaNotConnected(MetaConnectionError)` — status/operation requires a connection
- `MetaReturnUriInvalid(MetaConnectionError)` — disallowed return URI
- `MetaTokenEncryptionError(MetaConnectionError)` — missing/invalid encryption key

## Ports (`dojo/ports.py`)

```python
class MetaConnectionStore(Protocol):
    def get_active(self) -> MetaConnectionStatus | None: ...
    def upsert_active(self, conn: MetaConnectionRecord) -> MetaConnectionStatus: ...
    def get_attempt(self, attempt_id: str) -> MetaOAuthAttemptRecord | None: ...
    def create_attempt(self, attempt: MetaOAuthAttemptRecord) -> MetaOAuthAttemptRecord: ...
    def consume_attempt(self, attempt_id: str, at: datetime) -> MetaOAuthAttemptRecord | None: ...
    def mark_attempt_completed(self, attempt_id: str, candidates: list[MetaCandidate], enc_token: str | None, expires_at: datetime | None) -> None: ...
    def mark_attempt_failed(self, attempt_id: str, error: str) -> None: ...

class MetaOAuthProvider(Protocol):
    def build_auth_url(self, state: str, redirect_uri: str) -> str: ...
    def exchange_code(self, code: str, redirect_uri: str) -> tuple[str, datetime]: ...  # token, expires_at
    def exchange_long_lived(self, short_token: str) -> tuple[str, datetime]: ...
    def list_eligible_accounts(self, long_token: str) -> list[MetaCandidate]: ...
    def refresh_token(self, long_token: str) -> tuple[str, datetime]: ...
    def inspect_token(self, token: str) -> tuple[bool, datetime | None]: ...  # valid, expires_at

class TokenCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...
```

Internal `MetaConnectionRecord` / `MetaOAuthAttemptRecord` carry encrypted token fields; only `MetaConnectionStatus` (no ciphertext) crosses the facade interface. `InMemoryStore` and `PostgresStore` implement `MetaConnectionStore`; `FernetCipher` and `StubMetaOAuthProvider` satisfy `TokenCipher`/`MetaOAuthProvider` at test seams.

## Facade (`dojo/meta_connection.py`)

```python
class DojoMetaConnection:
    def __init__(self, *, store: MetaConnectionStore, provider: MetaOAuthProvider,
                 cipher: TokenCipher, clock: Clock | None = None,
                 app_id: str, app_secret: str, redirect_uri: str,
                 graph_version: str, allowed_return_uris: list[str]): ...

    def start(self, client_id: int, return_uri: str | None = None) -> str: ...  # returns auth_url
    def complete_callback(self, state: str, code: str) -> str: ...  # returns attempt_id
    def get_attempt(self, client_id: int, attempt_id: str) -> MetaOAuthAttempt: ...
    def select_account(self, client_id: int, attempt_id: str, ig_user_id: str) -> MetaConnectionStatus: ...
    def get_status(self) -> MetaConnectionStatus: ...
    def maintain(self) -> MetaConnectionStatus: ...
    # internal for #18
    def get_valid_token(self) -> str | None: ...
```

Rules:
- `start` validates `return_uri` against allowlist, generates random state, stores `hash(state)` + client + TTL, returns provider `build_auth_url`.
- `complete_callback` validates state hash/expiry/single-use, exchanges code→short token→long token, discovers candidates, stores candidates + encrypted long token on the attempt, marks attempt `completed`; provider failure marks `failed` with sanitized error. No active row mutated.
- `get_attempt` enforces same-client access; expired attempts become `expired`.
- `select_account` validates active candidates, verifies `ig_user_id` eligible, decrypts attempt token, re-validates via provider, atomically upserts active connection, expires attempt, audits `meta.connected` / `meta.reconnected`.
- `get_status` derives `refresh_due` when `expires_at - now <= 7d`; otherwise reflects stored health.
- `maintain` is idempotent, at-most daily remote check, refresh-then-validate, fail-closed on DB/cipher errors, never mutates package/schedule state. Definitive failure → `reconnect_required`; transient failure → preserves health with `last_error`.

## Persistence

Migration `0012_meta_connection` adds:

- `meta_connections` — singleton active row:
  - `id` integer PK (check `id=1`)
  - `ig_user_id` text not null, `ig_username` text not null
  - `page_id` text not null, `page_name` text not null
  - `encrypted_token` text not null
  - `token_expires_at` timestamptz not null
  - `health` text not null
  - `last_checked_at` timestamptz null, `last_refreshed_at` timestamptz null
  - `last_error` text null
- `meta_oauth_attempts`:
  - `id` text PK (UUID)
  - `state_hash` text not null unique, `initiated_by_client_id` int FK `clients.id`
  - `return_uri` text null
  - `status` text not null, `created_at` timestamptz not null, `expires_at` timestamptz not null
  - `candidates` JSON null, `encrypted_temp_token` text null, `temp_token_expires_at` timestamptz null
  - `last_error` text null
  - index on `state_hash`, `expires_at`

Add `meta_oauth_attempts` + `meta_connections` to `conftest` truncate list (connections last).

## FastAPI Integration

`backend/src/backend/routes/meta.py`:

- `POST /api/meta/oauth/start` — body `{return_uri?: str}`; auth required; 422 on disallowed URI; returns `{auth_url, attempt_id?}` (or just `auth_url` with state embedded; attempt lookup via `attempt_id` from callback).
- `GET /api/meta/oauth/callback?code&state` — public (state-authenticated, outside `get_current_client`); 400 on invalid/expired/reused state; exchanges/discovery; redirects to allowlisted `return_uri?attempt_id=…` when present else returns JSON `{attempt_id}`; provider rejection → 502 with sanitized detail, never leaks token/state/code.
- `GET /api/meta/oauth/attempts/{attempt_id}` — auth required; same-client check; 404/410 on unknown/expired.
- `POST /api/meta/oauth/attempts/{attempt_id}/select` — body `{ig_user_id}`; auth required + same-client; 422 on ineligible account; success atomically replaces active connection.
- `GET /api/meta/status` — auth required; returns `MetaConnectionStatus` fields only.

No token/code/state/secret/encrypted payload ever appears in responses, logs, or audit details.

## Worker Integration

`worker/src/worker/main.py:run_tick` calls `meta.maintain()` before `publishing.evaluate_due_work()` and `publishing.send_due_reminders()`; failure is logged/audited with sanitized reason, never mutates package/schedule state. `DojoPublishing.publish` (issue #18) will check `meta.get_status().health != reconnect_required` before publication.

## Setup Integration

`DojoSetup` accepts optional `meta: DojoMetaConnection | MetaConnectionStore`; `checklist()` adds `instagram` item: complete when `health in (healthy, refresh_due)`. `is_ready()` includes it once wired.

## Configuration

Environment (backend + worker):
- `META_APP_ID`, `META_APP_SECRET`, `META_REDIRECT_URI`, `META_GRAPH_VERSION` (default `v19.0`), `META_TOKEN_ENCRYPTION_KEY` (required, 32-byte base64url Fernet key), `META_ALLOWED_RETURN_URIS` (comma-separated allowlist, must include web origin and Android deep-link prefix), `META_OAUTH_SCOPE` (default `instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement`).

Missing production secrets fail `DojoMetaConnection` construction fail-closed.

## Testing

### Domain (`dojo-core/tests/test_meta_connection.py`, in-memory + `FakeClock` + `StubMetaOAuthProvider` + `FernetCipher` with fixed key)
1. State single-use/hash/expiry/client-bound.
2. Multiple candidates → explicit selection succeeds; implicit auto-select disallowed.
3. Tokens ciphertext-only; status/attempt payloads contain no plaintext token/state/code.
4. Atomic reconnect — failed/abandoned attempt leaves prior active row unchanged; success atomically replaces.
5. Expiry derivation and 7-day `refresh_due` window.
6. `maintain` daily validation, refresh success, definitive failure → `reconnect_required`, transient outage preserves health with sanitized error.
7. Restart persistence — fresh facade over same store retains active status and attempt expiry.

### Contract (`backend/tests/test_meta_api.py`, FastAPI + in-memory)
- Auth on start/attempt/select/status (401); callback 400 on bad state; same-client enforcement.
- Allowlisted return URI accepted, disallowed → 422; callback redirects only to allowlisted URI.
- Candidate and status responses contain only safe fields.

### Store (`dojo-core/tests/test_store_meta.py` + `test_db_adapter.py`)
- Singleton replacement, attempt lifecycle (create→consume→complete/fail/expire).
- Encrypted column present, plaintext never persisted.

### Provider (`dojo-core/tests/test_meta_provider.py`, injected mock HTTP transport)
- Auth URL, code exchange, long-lived exchange, candidate discovery, refresh, inspect mapping without live Meta calls.

### Worker / Setup
- Worker seam: `maintain` runs before schedule/reminder work; failure does not mutate package state.
- Setup seam: Instagram checklist complete only for `healthy`/`refresh_due`.

Focused tests and mypy per slice; full suite + ruff + all package typechecks once at end. No React/Android implementation in #17; existing #26/#31 and #32/#38 consume these contracts.

## Out of Scope

- Publication execution, signed URLs, container/media IDs, polling before retry — #18.
- Publication failure recovery and `-publishing` retention — #19.
- React and Android UI for connect/picker/status/reconnect — consumed via HTTP contracts by #26/#31 and #32/#38.
- Multi-account, per-device roles, password storage, or browser automation.
- Multi-worker scheduler leadership — #21.
