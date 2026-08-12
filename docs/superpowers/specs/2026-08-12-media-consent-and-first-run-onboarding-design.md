# Media-Consent Policy and Guided First-Run Onboarding — Design

Date: 2026-08-12
Source: Issue #5 (part of #1, Dojo Reel Publishing MVP), blocked by #3 (done).

## Problem

Before scheduling starts, an installation needs guided first-run setup: pairing,
Instagram connection, schedule, consent policy, logo, caption template, and
optional cards. The media-consent policy must be accepted once per policy
version — one installation-wide acceptance recorded per version — with
responsibility for publishing student media explicit and auditable, and newly
paired clients inheriting the current acceptance.

## Decisions

1. **Seam placement**: new deep `DojoSetup` facade in `dojo-core`
   (`dojo/setup.py`), alongside `DojoPairing`, `DojoPublishing`, and
   `DojoActivity`. It owns the policy lifecycle, per-version acceptance
   recording, the derived onboarding checklist, and the `is_ready` scheduling
   gate. FastAPI routes and the worker scheduler share it.
2. **Scope now**: the installable policy + acceptance substructure, the
   onboarding checklist (pairing + consent items only today), the Setup API, and
   a CLI to set the policy. The Instagram, schedule, logo, caption-template, and
   cards checklist items arrive with their own tickets (#17/#13/#11/#6) and
   extend the same checklist; the worker scheduler gate consumes `is_ready` in
   #13.
3. **Policy is installation-wide and DB-backed**: one current policy = the
   highest `version`. `set_policy` creates a new version or replaces the text of
   the *same* version idempotently; a version lower than the current max is
   rejected (no downgrade). `created_by` records the acting client id or
   `"cli"`.
4. **Acceptance is once per policy version, inherited by every client**:
   exactly one `ConsentAcceptance` row per `policy_version`, storing
   `accepted_at` and a snapshot of the accepting client (id, name, kind).
   Recording is idempotent — re-accepting the same version returns the existing
   acceptance. Newly paired clients need no per-client consent rows; they
   inherit the current version's acceptance.
5. **Checklist is derived, not stored**: `checklist()` computes items from real
   state. `pairing` is complete when at least one non-revoked client exists
   (via `PairingStore.list_clients`); `consent` is complete when the current
   policy version has an acceptance. Future items plug into the same derivation.
6. **Scheduling gate**: `is_ready()` is true when every checklist item is
   complete. The worker scheduler (#13) calls it before emitting due work; no
   scheduling exists yet in this ticket.
7. **Audit**: consent policy updates and acceptances are auditable with the
   acting client attributed. New client actions: `consent.policy_updated`,
   `consent.accepted`.
8. **Auth**: all Setup API routes sit behind `get_current_client`, same as
   every other `/api` business route. Both paired kinds (device + browser) have
   equal access.

## Domain model

New models in `dojo/model.py`:

- `ConsentPolicy`: `version: int`, `text: str`, `created_at: datetime`,
  `created_by: str`, `id: int = 0`.
- `ConsentAcceptance`: `policy_version: int`, `accepted_at: datetime`,
  `accepting_client_id: int`, `accepting_client_name: str`,
  `accepting_client_kind: str`, `id: int = 0`.
- `SetupItem`: `key: str`, `label: str`, `complete: bool`.

## Storage

Migration `0003_setup` adds:

- `consent_policies`: id PK, version (unique int), text, created_at,
  created_by.
- `consent_acceptances`: id PK, policy_version (unique int, references consent
  policies), accepted_at, accepting_client_id, accepting_client_name,
  accepting_client_kind.

`SetupStore` (`dojo/ports.py`) contract:

- `create_policy(version, text, created_by, created_at) -> ConsentPolicy`
- `get_current_policy() -> ConsentPolicy | None`
- `get_policy(version: int) -> ConsentPolicy | None`
- `find_acceptance(policy_version: int) -> ConsentAcceptance | None`
- `record_acceptance(acceptance: ConsentAcceptance) -> bool` (unique-per-version;
  false when the version already has an acceptance)

`PostgresStore` implements it with unique constraints on `version` and
`policy_version`; `InMemoryStore` mirrors it. `conftest.py` adds the two new
tables to the TRUNCATE list.

## Ports

- `SetupStore(Protocol)` as above.
- Reuses `PairingStore.list_clients` for the pairing checklist item.

## Facade (`dojo/setup.py`)

`DojoSetup(setup: SetupStore, auditing: AuditStore, pairing: PairingStore)`:

- `current_policy() -> ConsentPolicy | None` — the highest version.
- `set_policy(*, version: int, text: str, requester: str) -> ConsentPolicy` —
  create or replace same-version text; reject downgrade; audit
  `consent.policy_updated`.
- `accept_current_policy(*, client: Client) -> ConsentAcceptance` — accept the
  current policy version; idempotent; when current policy is None raises
  `NoConsentPolicy`; audit `consent.accepted`.
- `checklist() -> list[SetupItem]` — pairing + consent items derived from state.
- `is_ready() -> bool` — all checklist items complete.

### Rules

- `set_policy` with `version < current.version` raises `ConsentPolicyDowngrade`.
- Recording an acceptance for a version that already has one is a no-op
  returning the existing record (no duplicate row, no duplicate audit event).
- `pairing` complete ⟺ any non-revoked client exists.
- `consent` complete ⟺ `find_acceptance(current_policy.version)` is not None.

## FastAPI integration

New router `backend/routes/setup.py` under `/api/setup`:

- `GET /api/setup` — auth required. Response:
  `{"checklist": [{"key", "label", "complete"}], "ready": bool}`
- `GET /api/setup/consent` — auth required. Response:
  `{"version": 1, "text": "...", "accepted_at": "..."|null}`
  (404 when no policy is configured)
- `POST /api/setup/consent/accept` — auth required, body empty. Records
  acceptance of the current version; returns `{"version", "accepted_at"}`.
  Idempotent.

`create_app` builds `DojoSetup` from the shared store and exposes it as
`app.state.setup`; the router reads it via request state. No new path needs
`pairing` in `DojoSetup` beyond what `deps.build_setup` wires.

## CLI

`backend/cli.py` gains a `dojo-consent` entry point (`set-policy --version N
--text "..."`), with requester `"cli"`. Wire the console script in
`backend/pyproject.toml`.

## Exceptions

- `ConsentPolicyDowngrade(DojoError)`.
- `NoConsentPolicy(DojoError)`.

## Testing

### Domain (`dojo-core/tests/test_setup.py`, in-memory + real Postgres)

1. `set_policy` creates the current policy; same version updates text in place;
   lower version raises `ConsentPolicyDowngrade`; actor recorded.
2. `accept_current_policy` records once per version, idempotent on re-accept,
   snapshot of accepting client; `NoConsentPolicy` when none configured.
3. New version requires a fresh acceptance (old acceptance does not satisfy the
   new version's checklist).
4. `checklist()`: pairing complete with a paired client, incomplete with none;
   consent complete only when the current version is accepted.
5. `is_ready()` gate toggles with both items.
6. Audit events `consent.policy_updated` and `consent.accepted` carry the acting
   client.
7. Postgres roundtrip + concurrent single acceptance via `pg_store`.

### Store (`dojo-core/tests/test_store_setup.py`, `test_db_adapter.py`)

- Policy roundtrip; `get_current_policy` returns highest version.
- `record_acceptance` unique per version; concurrent double-record yields one
  row.

### Contract (`backend/tests/test_api.py`, `test_cli.py`)

- Setup routes unauth → `401`.
- Paired device accepts consent, GET `/api/setup` reflects readiness, GET
  consent shows accepted status.
- `POST /api/setup/consent/accept` is idempotent over the HTTP surface.
- `set-policy` CLI writes a policy visible through the API.

## Out of scope

- Web/Android onboarding + consent UIs (tickets #26, #32).
- Instagram, schedule, logo, caption-template, and cards checklist items (#17,
  #13, #11, #6).
- Worker scheduler gating on `is_ready` (#13).