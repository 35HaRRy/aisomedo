# Pairing and Equal-Privilege Authorization — Design

Date: 2026-08-10
Source: Issue #3 (part of #1, Dojo Reel Publishing MVP), blocked by #2 (done).

## Problem

Pair trusted Android devices and browsers without user accounts. A short-lived
one-time code pairs either client; codes expire after one use and a short
period. Devices receive revocable bearer credentials; browsers receive secure
HttpOnly sessions. All paired clients have equal permissions, can be listed,
and can be revoked; revoked or stale credentials are denied.

## Decisions

1. **Seam placement**: separate `DojoPairing` deep facade in `dojo-core`
   (`dojo/pairing.py`), alongside `DojoPublishing`. It owns pairing flows and
   credential verification. FastAPI wires both facades; scheduler triggers never
   see HTTP auth. Shared store and audit live in the same DB.
2. **Bootstrap**: admin CLI command mints the first code
   (`python -m backend.cli create-code`, console script). Later codes are minted
   by any already-paired client through the API. No unauthenticated HTTP path
   mints codes.
3. **Code**: 8 chars from a 32-char alphabet (no `0/O/1/I`), 10-minute TTL,
   single-use (burned on success). A per-IP throttle (10 attempts/min) on the
   validate endpoint stops scripted guessing of leaked codes. A per-code
   wrong-try cap was rejected: with hash-only lookup a wrong attempt is a
   different string → no row to count against, so it would be a no-op.
4. **Device credential**: opaque bearer token (32 bytes, base64url), returned
   once at validate time, presented as `Authorization: Bearer`. Only its
   SHA-256 hash is stored. Revoke-only (no TTL).
5. **Browser credential**: opaque session id in a `HttpOnly`+`Secure`+
   `SameSite=Lax` cookie (env-controlled Secure flag for local http dev). Only
   its hash is stored; the row lives on the client. 30-day idle TTL (stale →
   denied); revocation kills it instantly.
6. **Equal permissions**: no roles. Any paired client can mint codes, list
   clients, and revoke any client.
7. **Audit**: DojoPairing writes attributed events. Bootstrap CLI acts as
   `cli`. DojoPublishing keeps `actor="system"` in this ticket; full threading
   of actors across all actions is ticket #4.
8. **Protected surface**: all `/api` routes except `/health` and the public
   pairing entrypoint (`POST /api/pairing/validate`) require a valid client.
9. **Lifetime**: device tokens revoke-only; browser sessions idle-expire after
   30 days.

## Domain model

New frozen dataclasses in `dojo/model.py`:

- `PairingCode`: `id`, `code_hash`, `expires_at`, `created_by`, `created_at`,
  `consumed_at` (nullable).
- `PairingCodeIssued`: `raw_code`, `expires_at` — what `create_pairing_code`
  returns to the caller (the raw code is never persisted).
- `Client`: `id`, `name`, `kind` (`"device"`|`"browser"`), `created_at`,
  `created_by`, `last_seen_at` (nullable), `revoked_at` (nullable).

Raw codes, bearer tokens, and session ids are never persisted — only SHA-256
hashes.

## Storage

Two new tables in `dojo/adapters/db.py` (rows on `Base`, Alembic migration
`0002_pairing`):

- `pairing_codes`: `code_hash` (unique, indexed), `expires_at`, `created_by`,
  `created_at`, `consumed_at`.
- `clients`: `name`, `kind`, `created_at`, `created_by`, `credential_hash`
  (unique, indexed), `last_seen_at`, `revoked_at`.

One `clients` row per pairing. A browser's session id hashes into the client's
`credential_hash`, same as a device's token. Re-pairing creates a new row; the
old one can be revoked independently.

`InMemoryStore` (tests) gains the same pairing surface; `PostgresStore`
implements both the existing store and `PairingStore`.

## Ports (`dojo/ports.py`)

- `PairingStore(Protocol)`: `create_code`, `find_code_by_hash`,
  `mark_code_consumed(code_id, at) -> bool` (conditional, returns whether this
  call won the single-use), `find_client_by_id`, `create_client(client,
  credential_hash)`, `find_client_by_credential_hash`, `list_clients`,
  `mark_client_revoked`, `touch_client`.
- `Hasher(Protocol)`: `hash(secret) -> str` (SHA-256).
- `SecretGenerator(Protocol)`: `generate_code() -> str`, `generate_token() -> str`.
- Reuse `Clock`, `AuditStore`.

## Facade (`dojo/pairing.py`)

`DojoPairing(pairing: PairingStore, audit: AuditStore, clock, hasher, generator)`
with defaults wired to real adapters:

- `create_pairing_code(*, requester: str) -> PairingCodeIssued` — returns the
  raw code plus its expiry, stores only the hash. Audit
  `pairing.code_created`, actor=`requester` (`"cli"` from the bootstrap
  command, client id from the API).
- `validate_code(*, code, kind, name) -> PairingResult` — validates, burns the
  code on success, creates the client, returns `PairingResult(client_id, kind,
  raw_credential)` (token for device, session id for browser). Audit
  `pairing.client_paired`, actor = the code's `created_by`.
- `list_clients() -> list[Client]`.
- `revoke_client(*, client_id, requester) -> None` — idempotent no-op if
  already revoked. Audit `pairing.client_revoked`, actor=`requester`.
- `authenticate_bearer(token: str) -> Client | None`.
- `authenticate_session(session_id: str) -> Client | None`.

### Rules

- Code valid iff: not consumed and `now < expires_at`.
- Per-IP attempt throttle on the HTTP validate endpoint (10/min), not on the
  facade.
- Credential valid iff: client exists, `revoked_at` null, and (browser only)
  `now - last_seen_at <= 30d` idle TTL.
- Successful auth updates `last_seen_at` (both kinds).
- No role checks anywhere (equal permissions).

### Concurrency

- Single-use is enforced atomically: consume uses a conditional update
  (`UPDATE ... WHERE consumed_at IS NULL`); zero affected rows means the race
  was lost and the attempt is treated as invalid. In-memory store is
  single-threaded.

## Exceptions (`dojo/exceptions.py`)

`PairingError` base with `PairingCodeInvalid` (unknown), `PairingCodeExpired`,
`PairingCodeConsumed`, `ClientNotFound`. FastAPI maps:
- bad/expired/consumed code → `401` with a generic message (never reveals
  whether the code exists).
- unknown client on revoke/list/me → `404`.
- missing/revoked/stale credential → `401`.

## FastAPI integration

New router `backend/routes/pairing.py` under `/api/pairing`:

- `POST /codes` — auth required; any paired client mints a code. Returns
  `{code, expires_at, ttl_seconds}`.
- `POST /validate` — public; body `{code, kind, name}`. Device → `{client_id,
  kind, token}`. Browser → `{client_id, kind}` + `Set-Cookie` (HttpOnly,
  Secure, SameSite=Lax, Path=/, max-age 30d). Session id never in the body.
  Per-IP throttle: 10 attempts/min per remote IP (in-memory sliding window,
  per-process for MVP; backend runs as a single process behind the reverse
  proxy). Over limit → `429`.
- `GET /clients` — auth required; list with revoked flag.
- `POST /clients/{id}/revoke` — auth required; actor = current client.
- `GET /me` — auth required; current client.

Auth dependency `get_current_client(request)` in `backend/deps.py`:
`Authorization: Bearer` → `authenticate_bearer`; else `dojo_session` cookie →
`authenticate_session`; else `401`.

`create_app` builds both facades (one shared store). `packages` router and all
future business routers carry `dependencies=[Depends(get_current_client)]`.
`/health` stays public. `deps.build_pairing()` mirrors `build_publishing()`
and reads `DATABASE_URL` + `COOKIE_SECURE` (default true; off for local http).

## CLI bootstrap

`backend/src/backend/cli.py` (`python -m backend.cli create-code`, console
script `dojo-create-pairing-code`): builds the same store+facade as
`build_pairing()`, calls `create_pairing_code(requester="cli")`, prints the raw
code and expiry. Never logs the code.

## Testing

### Domain (`dojo-core/tests/test_pairing.py`, real Postgres + FakeClock)

1. Pair device → token authenticates.
2. Pair browser → session authenticates.
3. Single-use: second validate with the same code fails.
4. Expiry: clock past TTL → fails.
5. Browser idle TTL: > 30 days idle → denied; activity resets it.
6. Revoke device / browser → next authenticate denied.
7. `list_clients` shows both clients + revoked flag.
8. Equal permissions: one client mints codes and revokes the other.
9. Audit attribution: `code_created` actor=requester, `client_paired`
   actor=code creator, `client_revoked` actor=revoker.
10. Concurrency: two threads validate the same code on Postgres → exactly one
    wins.

### Contract (`backend/tests/test_api.py`, TestClient + in-memory stores)

- Validate device returns token; `/api/packages` 401 unauth / 200 with bearer /
  401 after revoke.
- Validate browser sets HttpOnly cookie; cookie-authed request works; revoked →
  401.
- `/me`; invalid code → 401.
- Per-IP throttle: 11th validate request within a minute → `429`.

### CLI

Thin smoke: `create-code` with `requester="cli"` audits actor `cli`.

Alembic `0002_pairing` migration matches `Base.metadata`.

## Out of scope

- Roles / per-device permissions (spec: none in MVP).
- Threading actors through DojoPublishing actions (ticket #4).
- Web/Android pairing UIs (tickets #25, #32).
- Cross-process / distributed rate limiting (MVP runs a single backend process;
  the in-memory per-IP window is per-process).
