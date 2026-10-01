# Web Onboarding and Consent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #26 with resumable Turkish onboarding, direct Instagram access-token entry, version-safe consent, and backend-derived completion.

**Architecture:** Extend the existing setup, publishing, and Meta facades rather than introduce another service. Independent branding assets and partial settings operations feed a step-based wizard inside the current session-protected shell; OpenAPI generates browser DTOs.

**Tech Stack:** Existing Python 3.12, FastAPI/Pydantic, SQLAlchemy/PostgreSQL, Pillow, React 18/TypeScript/Vite, pytest, Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-01-web-onboarding-consent-design.md` (user approved).

## Global Constraints

- All seven first-run items are visible; backend state alone determines required completion.
- Optional cards never prevent readiness; valid disabled plans are configured, not enabled.
- Monday anchor, biweekly cadence, and `Europe/Istanbul` remain unchanged.
- User-entered Instagram `access_token` is submitted to the existing backend endpoint; no browser-side Instagram API calls.
- Token text never enters browser storage, URLs, navigation state, analytics, error text, or logs; clear after every submission attempt and unmount.
- New consent requests send the displayed version; stale versions return HTTP 409 without accepting the new policy.
- Legacy bodyless consent and full branding PUT remain compatible; no Android minimum-version bump.
- PNG/JPEG onboarding uploads only: maximum 10 MiB and 4096 pixels per side; server-generated immutable paths and authenticated previews.
- Installation branding updates never mutate existing package snapshots; replaced files are retained.
- All new user-facing strings live in the Turkish catalog; preserve existing shell, session, accessibility, and foreground-refresh patterns.
- Regenerate committed OpenAPI, TypeScript, and Kotlin artifacts; do not hand-edit generated files.
- No package-upload UI, caption interpolation, policy editor, Android onboarding, or automatic asset garbage collection.

## Review Focus

- A new policy committed while acceptance waits must reject the old displayed version, including PostgreSQL and memory adapters (Task 2).
- Omitted fields and explicit null differ; another step's branding values must survive partial saves (Task 3).
- PNG/JPEG signatures with truncated contents, deceptive MIME, excessive dimensions, or symlink escapes must not install unsafe assets (Task 4).
- Background changes must update status without overwriting dirty input or accepting a changed policy with an old acknowledgement (Tasks 6–8).
- A session revoked during token submission or upload must discard late responses, clear protected data, and stop OAuth polling (Tasks 6–8).

## File responsibilities

- `dojo-core/src/dojo/setup.py`, `model.py`: complete ordered checklist, required flags, optional-card review marker, consent facade.
- `dojo-core/src/dojo/ports.py`, `adapters/{memory,db}.py`: serialized consent acceptance and policy updates.
- `dojo-core/src/dojo/publishing.py`: partial branding persistence preserving existing snapshots.
- New `dojo-core/src/dojo/branding_assets.py`: bounded raster validation and immutable asset storage/resolution.
- `backend/src/backend/routes/{setup,settings,meta}.py`, new `branding_assets.py`: thin authenticated operations and DTOs.
- `backend/src/backend/main.py`: asset-router registration; existing startup wiring remains intact.
- `backend/scripts/generate_clients.py`: additional schema roots; retain existing compatibility exports.
- New `web/src/onboarding/{types,state,useOnboarding,OnboardingWizard}.ts[x]`: progress, dirty/saving lifecycle, and guided navigation.
- New `web/src/onboarding/{InstagramStep,ConsentStep,PlanStep,BrandingStep,CardsStep}.tsx`: focused forms.
- `web/src/{App.tsx,navigation.ts,styles.css}`, `components/SettingsSummary.tsx`, `api/client.ts`, `i18n/tr.ts`: integrate the wizard with current shell.
- Tests alongside each new web module and in existing Python test directories; `docs/verification/issue-26-web-onboarding.md` records actual acceptance evidence.

## Task 1: Authoritative seven-item checklist

**Files:** Modify `dojo-core/src/dojo/{model,setup}.py`, `dojo-core/tests/test_setup.py`, readiness fixtures in `dojo-core/tests/test_schedule.py`, `backend/tests/test_api.py`, and worker scheduler tests that depend on setup readiness. Create `dojo-core/tests/test_onboarding.py`.

**Interfaces:**
- Extend `SetupItem(key: str, label: str, complete: bool, required: bool = True)`.
- Preserve `DojoSetup.checklist() -> list[SetupItem]` and `is_ready() -> bool`.
- Add `DojoSetup.skip_cards(*, requester: str) -> None`, storing `setup.cards_reviewed = True` through the existing settings store and auditing `setup.cards_reviewed`.
- Ordered keys: `pairing`, `instagram`, `schedule`, `consent`, `logo`, `caption_template`, `cards`; only cards has `required=False`.

- [ ] **1. Write `test_checklist_has_all_seven_items_and_optional_cards`:** assert exact ordered keys, missing Meta produces incomplete Instagram, cards is optional, and completing the six required entries makes `is_ready()` true with cards still incomplete. Add `test_valid_disabled_monday_plan_is_configured`, `test_whitespace_branding_is_incomplete`, and `test_skip_cards_persists_without_changing_branding` with these assertions.
- [ ] **2. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_onboarding.py -v`; expect missing keys/method failures.
- [ ] **3. Implement checklist and skip action:** safely parse persisted anchor date/time, require Monday, reject malformed values as incomplete, and do not conflate `schedule.enabled` with configuration. Cards complete when reviewed marker is true or valid card configuration exists. Existing nonempty legacy asset references stay compatible. Skipping reviews the optional step; it does not remove installed cards. Removal belongs to explicit branding edits.
- [ ] **4. Update readiness-dependent fixtures:** configure a healthy fake Meta connection and valid plan where tests intend readiness. Keep tests for disabled scheduling and unmet setup asserting no scheduling, rather than weakening gates.
- [ ] **5. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_onboarding.py dojo-core/tests/test_setup.py dojo-core/tests/test_schedule.py -v`; `uv run --project backend pytest backend/tests/test_api.py -v`; `uv run --project worker pytest worker/tests -v`. Expect PASS; record unavailable Docker/PostgreSQL prerequisites separately.
- [ ] **6. Commit scoped files:** `feat(core): track complete onboarding checklist`.

## Task 2: Serialized displayed-version consent acceptance

**Files:** Modify `dojo-core/src/dojo/{setup,ports,exceptions,__init__}.py`, `dojo-core/src/dojo/adapters/{memory,db}.py`, `dojo-core/tests/test_setup.py`, `dojo-core/tests/test_store_setup.py`. Create `dojo-core/tests/test_consent_version.py`.

**Interfaces:**
- Export `ConsentPolicyChanged(DojoError)`.
- Extend `DojoSetup.accept_current_policy(*, client: Client, version: int | None = None) -> ConsentAcceptance`.
- Add `SetupStore.accept_policy_version(*, client: Client, version: int | None, accepted_at: datetime) -> tuple[ConsentAcceptance, bool]`; boolean means this call inserted the acceptance.
- Preserve existing `record_acceptance` for compatibility; facade uses the new operation. Facade audits only when insertion boolean is true.

- [ ] **1. Write `test_displayed_version_rejects_new_policy`:** create v1, then v2, request v1, assert `ConsentPolicyChanged`, no acceptance for v2, and no acceptance audit. Add tests for missing-policy `NoConsentPolicy`, repeated-version idempotence, accepting client identity, and another client inheriting acceptance. Assert bodyless facade call still accepts current policy.
- [ ] **2. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_consent_version.py -v`; expect unsupported-version/missing-method failures.
- [ ] **3. Implement atomic adapters:** PostgreSQL `create_policy` and `accept_policy_version` acquire the same transaction advisory lock using `pg_advisory_xact_lock(hashtext('dojo.consent-policy'))`. Acceptance reads current policy, checks expected version, and reads/inserts acceptance before commit in that transaction. Memory uses one `RLock` shared by policy updates and acceptance. Preserve existing same-version policy-edit behavior; do not accept a different current version silently.
- [ ] **4. Write deterministic concurrency tests for both stores:** barriers/events arrange policy v2 commit before a waiting v1 acceptance can acquire the shared lock; assert rejection and no v2 acceptance. Concurrent same-version acceptances return the same record, with one insertion and one facade audit. Use existing `pg_store` fixture and independent store sessions, not sleep-based timing.
- [ ] **5. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_consent_version.py dojo-core/tests/test_store_setup.py dojo-core/tests/test_setup.py -v`; expect PASS, including PostgreSQL cases.
- [ ] **6. Commit scoped files:** `fix(core): bind consent to displayed policy version`.

## Task 3: Partial branding configuration

**Files:** Modify `dojo-core/src/dojo/{publishing,exceptions,__init__}.py`; create `dojo-core/tests/test_branding_patch.py`; preserve `dojo-core/tests/test_branding.py`.

**Interfaces:**
- Add `DojoPublishing.patch_branding_defaults(changes: dict[str, object], requester: str | None = None) -> BrandingConfig` and export `BrandingInvalid(DojoError)`.
- Accept only the six existing `BrandingConfig` fields. Omission leaves a field untouched; null clears it. Empty caption or logo string is invalid. Optional cards may be cleared; clearing an asset clears its paired duration.
- Card durations, when supplied, are positive finite numbers; omitted duration retains current setting; absent duration renders with the existing photo-duration default.

- [ ] **1. Write `test_caption_patch_preserves_logo_and_cards`, `test_null_card_clears_asset_and_duration`, and `test_patch_preserves_existing_package_snapshot`. Assert exact unchanged branding fields, existing manifest contents, and one `branding.defaults_updated` audit describing resulting safe defaults. Add rejection tests for whitespace captions, unknown keys, negative/zero/nonfinite durations, and invalid types without partial writes.
- [ ] **2. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_branding_patch.py -v`; expect missing patch method failure.
- [ ] **3. Implement validation before writes:** persist only explicitly changed or dependent-cleared keys rather than rewriting all current values. Keep full `set_branding_defaults` semantics unchanged. Never call draft setters or renderer on global updates.
- [ ] **4. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_branding_patch.py dojo-core/tests/test_branding.py -v`; expect PASS.
- [ ] **5. Commit scoped files:** `feat(core): add partial branding defaults updates`.

## Task 4: Independent safe branding image assets

**Files:** Create `dojo-core/src/dojo/branding_assets.py`, `dojo-core/tests/test_branding_assets.py`; modify `dojo-core/src/dojo/{exceptions,__init__}.py`.

**Interfaces:**
- `BrandingAssets(media_root: Path)` with `save_image(data: bytes) -> BrandingAsset` and `resolve(asset_id: str) -> Path`.
- Frozen `BrandingAsset(asset_id: str, reference: str, content_type: str)`; reference is `branding/assets/<uuid>.png` or `.jpg` under media root.
- Export `BrandingAssetInvalid`, `BrandingAssetTooLarge`, and `BrandingAssetNotFound` domain exceptions.

- [ ] **1. Write fixtures with existing Pillow:** `test_png_and_jpeg_roundtrip` asserts generated refs resolve to actual decoded images without an active package; 10 MiB + 1 byte rejects; 4097px in either dimension rejects; 4096px passes. Test empty/truncated files, non-image content, GIF/WebP/SVG, animated images, and filename/path traversal. Symlink escape preview must reject (skip only when platform cannot create symlinks, with reason).
- [ ] **2. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_branding_assets.py -v`; expect missing module failure.
- [ ] **3. Implement immutable assets:** decode and fully load PNG/JPEG with Pillow, limit bytes/dimensions, reject multi-frame content, normalize/re-encode validated image preserving PNG alpha, and install atomically under generated UUID names. Discard metadata. Validate asset IDs and resolved containment for reads; never trust client names or MIME. Never unlink replaced assets referenced by old packages. Reuse existing dependency, no new image library.
- [ ] **4. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_branding_assets.py dojo-core/tests/test_branding_patch.py -v`; expect PASS.
- [ ] **5. Commit scoped files:** `feat(core): store validated branding images`.

## Task 5: Authenticated APIs and generated contract

**Files:** Modify `backend/src/backend/routes/{setup,settings,meta}.py`, `backend/src/backend/main.py`, `backend/scripts/generate_clients.py`, `backend/tests/test_client_generation.py`; create `backend/src/backend/routes/branding_assets.py`, `backend/tests/test_onboarding_api.py`, `backend/tests/test_branding_assets_api.py`; regenerate `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`.

**Interfaces:**
- `SetupItemOut.required: bool = True`; setup GET includes Task 1 ordered checklist.
- `AcceptanceIn(version: int | None = None)` is optional body for existing accept POST; map `ConsentPolicyChanged` to 409 and `NoConsentPolicy` to 404.
- `POST /api/setup/cards/skip -> SetupOut` calls Task 1 then returns authoritative checklist.
- `PATCH /api/settings/branding`, `BrandingPatchIn` with six optional fields, uses `model_dump(exclude_unset=True)` and Task 3; invalid content returns 422. Full PUT unchanged.
- `POST /api/settings/branding/assets` receives raw bytes and returns 201 `BrandingAssetOut(asset: str, preview_url: str)`; `GET /api/settings/branding/assets/{asset_id}` returns authenticated image bytes. Stream with an enforced 10 MiB cap even if Content-Length is absent or false; invalid content 422, too large 413, absent/invalid preview ID 404.
- `MetaCandidateOut(ig_user_id: str, ig_username: str, page_id: str | None, page_name: str | None)` replaces untyped candidate dictionaries in `AttemptOut`; retain existing response fields.
- Existing token POST stays manually validated to avoid secret reflection; missing Meta configuration returns sanitized 503 rather than an attribute-error 500.

- [ ] **1. Write API tests using existing `make_app`/pairing helpers:** browser/device access works, unauthenticated/revoked access is 401, versioned accept is idempotent, bodyless POST remains supported, stale version gives 409 without acceptance, no policy gives 404. Assert `required` flags, skip persistence, partial-save preservation, and Monday-plan validation.
- [ ] **2. Write asset and token API tests:** bounded streaming, MIME deception handled by actual content, private preview, path containment, default values unchanged after upload/save rejection, and successful asset reference resolves through existing renderer. Token success returns account health only; invalid token 422/provider outage 502/unconfigured Meta 503 expose no submitted secret or exception payload. Failed reconnect retains prior safe status. Invalid PATCH input cannot install arbitrary filesystem paths: new asset values must be generated existing references; omitted legacy values survive.
- [ ] **3. Run:** `uv run --project backend pytest backend/tests/test_onboarding_api.py backend/tests/test_branding_assets_api.py -v`; expect missing operations/validation failures.
- [ ] **4. Implement thin routes:** use current-client dependency on all new operations. Construct asset facade from publishing media root; register asset router in `main.py`. Add typed candidates without changing account-selection semantics. Keep token validation outside ordinary Pydantic error reflection.
- [ ] **5. Extend generator roots:** add `SetupOut`, `ConsentOut`, `AcceptanceIn`, `AcceptanceOut`, `BrandingDefaultsOut`, `BrandingPatchIn`, `BrandingAssetOut`, `PlanIn`, `PlanOut`, `StatusOut`, `StartIn`, `StartOut`, `AttemptOut`, `SelectIn`. Add tests for omission vs nullable fields and typed candidate closure. Preserve existing Kotlin output contract; regenerate it even if bytes remain unchanged.
- [ ] **6. Run export and generation separately:** `uv run --project backend python backend/scripts/export_openapi.py`; `uv run --project backend python backend/scripts/generate_clients.py`. Then run `uv run --project backend pytest backend/tests/test_onboarding_api.py backend/tests/test_branding_assets_api.py backend/tests/test_client_generation.py backend/tests/test_contract.py backend/tests/test_api.py -v`; expect PASS.
- [ ] **7. Commit scoped files:** `feat(api): expose guided setup operations`.

## Task 6: Wizard transport, progress state, and shell integration

**Files:** Modify `web/src/api/{client.ts,client.test.ts}`, `web/src/{App.tsx,App.test.tsx,navigation.ts}`, `web/src/components/SettingsSummary.tsx`, `web/src/test/fixtures.ts`; create `web/src/onboarding/{types.ts,state.ts,state.test.ts,useOnboarding.ts,useOnboarding.test.tsx,OnboardingWizard.tsx,OnboardingWizard.test.tsx}`.

**Interfaces:**
- `OnboardingStep = "pairing" | "instagram" | "schedule" | "consent" | "logo" | "caption_template" | "cards"`; `firstIncompleteRequired(checklist: SetupItemOut[]) -> OnboardingStep | null`.
- Add typed `api.setup`, `consent`, `acceptConsent(version, signal?)`, `skipCards(signal?)`, `branding`, `patchBranding(body, signal?)`, `plan`, `savePlan(body, signal?)`, `instagram`, `connectInstagramToken(token, signal?)`, `startOAuth(signal?)`, `oauthAttempt(id, signal?)`, `selectInstagramAccount(id, igUserId, signal?)`, `uploadBranding(file: File, signal?)` with DTO return types from Task 5.
- `request<T>` remains compatible; default JSON Content-Type only for JSON bodies, not raw File/Blob uploads. Keep existing abort, timeout, and same-origin behavior.
- `OnboardingProvider({children}: {children: ReactNode})` wraps the paired shell once per session generation; `useOnboarding()` reads its shared context exposing `setup`, `error`, `refresh()`, and `save<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T>`. One provider owns setup polling and save cancellation; steps do not start duplicate setup pollers. Per-step dirty drafts stay in step forms, not persisted.
- Add `onboarding` to `Area`; hash `#/onboarding`. Keep four primary nav areas. `OnboardingWizard()` renders ordered progress and step heading; Settings link reopens it.

- [ ] **1. Write state/client tests:** authoritative checklist selects first required incomplete step; all required complete does not force optional cards complete. Assert each endpoint/method/body, generated DTO use, raw-file upload Content-Type, cookie credentials, abort behavior, and displayed version in acceptance JSON. Token request is POST body only, never URL/storage.
- [ ] **2. Run:** `npm test -- src/onboarding/state.test.ts src/api/client.test.ts` in `web`; expect absent exports/method failures.
- [ ] **3. Implement transport and hook:** reuse existing refresh controller (5000ms, focus/visibility refresh, hidden/offline pause). After successful saves refresh authoritative setup; refresh failure must be visibly retryable, not synthesize completion. Ignore obsolete responses and invalidate on protected mutation 401.
- [ ] **4. Write shell tests:** incomplete setup opens first unfinished step once per paired generation; intentional Dashboard navigation survives future ticks; reload resumes; ready installation stays Dashboard; direct route and Settings reopen work. Primary navigation remains four areas. Failed initial setup read shows error rather than redirecting on fabricated state. Add revoked-session/late-save response tests. Existing generic fetch mocks must explicitly serve `/api/setup` rather than return dashboard DTOs for every unknown route.
- [ ] **5. Run shell tests red, then integrate wizard:** conditionally render onboarding independently of dashboard availability. Retain shell loading/error notices and skip-link behavior. Do not leave a dangling failed dashboard request blocking setup.
- [ ] **6. Run:** `npm test -- src/onboarding/state.test.ts src/onboarding/useOnboarding.test.tsx src/onboarding/OnboardingWizard.test.tsx src/api/client.test.ts src/App.test.tsx`; `npm run typecheck`. Expect PASS.
- [ ] **7. Commit scoped files:** `feat(web): add resumable onboarding shell`.

## Task 7: Instagram access-token/OAuth and consent steps

**Files:** Create `web/src/onboarding/{InstagramStep.tsx,InstagramStep.test.tsx,ConsentStep.tsx,ConsentStep.test.tsx}`; modify `OnboardingWizard.tsx`, `web/src/i18n/tr.ts`.

**Interfaces:**
- `InstagramStep({onSaved}: {onSaved: () => void})` consumes Task 6 API/hook and displays safe `StatusOut`.
- `ConsentStep({onSaved}: {onSaved: () => void})` loads `ConsentOut`, submits exact `version`, and displays `AcceptanceOut`.
- Exact manual form labels: `Instagram erişim tokenı`, `Token ile bağlan`; invalid credentials and provider failure use separate Turkish catalog messages.

- [ ] **1. Write token tests:** masked labelled input accepts externally obtained token, sends exact token body through Task 6 method, disables duplicate submit, clears after success/rejection/outage, and displays verified username/health. Assert no local/session storage writes and no token in error DOM, URL, or state after unmount. Session loss discards late success and clears field.
- [ ] **2. Write OAuth tests:** explicit initiation opens authorization URL in new window, no return URI is fabricated; foreground attempt polling stops on cleanup/session loss. Completed attempt with two candidates requires explicit choice; expiry/failure/unknown attempt offers retry; popup-blocked path shows open link; abandoned reconnect preserves previous account display.
- [ ] **3. Run:** `npm test -- src/onboarding/InstagramStep.test.tsx`; expect missing step behavior failure, then implement only the tested flow. Use safe new-window links (`noopener`) and no credential persistence; show configuration-unavailable copy for 503.
- [ ] **4. Write consent tests:** policy is plain text, acknowledgement initially unchecked, accepted policy shows timestamp without resubmission, repeated submit disabled, no policy blocks safely. Version 1 changing to 2 resets acknowledgement even during live refresh; submit v1 receiving 409 reloads v2 without auto-acceptance. Provider text containing HTML renders as text, not markup. Another device's acceptance updates state without unnecessary new acceptance.
- [ ] **5. Run:** `npm test -- src/onboarding/ConsentStep.test.tsx`; expect missing behavior, then implement version-aware state. Treat missing policy 404 as a legitimate blocked state, not perpetual generic loading.
- [ ] **6. Run:** `npm test -- src/onboarding/InstagramStep.test.tsx src/onboarding/ConsentStep.test.tsx src/onboarding/OnboardingWizard.test.tsx`; `npm run typecheck`. Expect PASS.
- [ ] **7. Commit scoped files:** `feat(web): add Instagram and consent onboarding`.

## Task 8: Plan, logo, caption, optional cards, and accessible completion

**Files:** Create `web/src/onboarding/{PlanStep.tsx,PlanStep.test.tsx,BrandingStep.tsx,BrandingStep.test.tsx,CardsStep.tsx,CardsStep.test.tsx}`; modify `web/src/onboarding/{types.ts,OnboardingWizard.tsx,OnboardingWizard.test.tsx}`, `web/src/i18n/tr.ts`, `web/src/styles.css`.

**Interfaces:**
- `PlanStep({onSaved}: {onSaved: () => void})` consumes plan DTOs and Task 6 methods.
- `BrandingStep({kind,onSaved}: {kind: "logo" | "caption_template"; onSaved: () => void})` performs only its field's partial update.
- `CardsStep({onSaved}: {onSaved: () => void})` uploads intro/outro, edits positive finite durations, explicitly clears cards, or marks step reviewed via skip without deleting existing settings.
- Each form maintains dirty draft state; foreground data refresh changes safe status but offers explicit reload before replacing dirty inputs. Completion summary uses server checklist; finish navigates to Dashboard.

- [ ] **1. Write plan tests:** Monday `2026-10-05` accepted, Tuesday `2026-10-06` rejected before submission, time and enabled flag saved; display `Europe/Istanbul` and biweekly rule. Backend 422 keeps draft and does not advance. Disabled valid plan renders configured but disabled.
- [ ] **2. Run plan tests red, then implement labelled date/time/enable inputs** with inline errors and pending-submit state. Do not add another cadence or timezone selector.
- [ ] **3. Write branding tests:** valid upload then partial logo save, authenticated preview, caption-only patch preserves cards/logo, whitespace caption rejected, unsupported/oversized image blocked, backend invalid/dimension error keeps previous defaults. Another-device refresh while dirty does not replace typed text. Explicit reload adopts fresh values. Upload completing after revocation does not install an asset.
- [ ] **4. Run branding tests red, then implement:** use Task 6 uploads and generated refs, not local paths. Upload/install are separate; display failures separately and retain prior saved preview until installation succeeds. Legacy references without generated previews show configured status rather than broken images or raw filesystem paths.
- [ ] **5. Write cards and complete-flow tests:** no cards -> skip marker survives reload and readiness; existing cards still display after skip; explicit remove clears asset/duration. Positive decimal duration succeeds, zero/negative/nonfinite rejected. Reaching required readiness does not auto-close wizard before optional step; finish returns Dashboard. Keyboard interaction focuses new step heading, progress uses current-step semantics, errors are announced.
- [ ] **6. Run cards/wizard tests red, then implement controls and responsive styling:** reuse existing shell visual language, visible focus, wrapping long Turkish labels/names, status text independent of color. Step components stay small; extract reusable field/status pieces only where duplicated.
- [ ] **7. Run:** `npm test`; `npm run typecheck`; `npm run build` in `web`. Expect all tests and production bundle PASS.
- [ ] **8. Commit scoped files:** `feat(web): complete guided setup configuration`.

## Task 9: Acceptance evidence and regression checks

**Files:** Create `docs/verification/issue-26-web-onboarding.md`; modify `README.md` with onboarding, manual-token, branding-image limits, and policy-version behavior. Adjust earlier files only for demonstrated defects.

**Interfaces:** Complete issue #26 acceptance criteria; no new product interface. Existing CI already runs Python suites, web tests/build, and contract drift; do not add redundant jobs.

- [ ] **1. Run full Python suites separately:** `uv run --project dojo-core pytest dojo-core/tests -v`; `uv run --project backend pytest backend/tests -v`; `uv run --project worker pytest worker/tests -v`. Record actual counts and failed/skipped tests; missing Docker/FFmpeg is a blocker, not a pass.
- [ ] **2. Run Python checks separately:** `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests`; `uv run --project backend ruff check backend/src backend/tests`; `uv run --project worker ruff check worker/src worker/tests`; `uv run --project dojo-core mypy dojo-core/src/dojo`; `uv run --project backend mypy backend/src/backend`; `uv run --project worker mypy worker/src/worker`. Expect zero errors, distinguish baseline failures.
- [ ] **3. Run web checks in `web`:** `npm test`; `npm run typecheck`; `npm run build`. Expect PASS. If isolated execution has no dependencies, use `npm ci` before these checks.
- [ ] **4. Regenerate contract twice:** use Task 5 export/generation commands, then `git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`. Expect no drift after generated artifacts have been committed.
- [ ] **5. Browser acceptance with deterministic fixtures:** verify 320px, 390px, 1280px widths, keyboard-only full wizard, manual token success/rejection, OAuth picker, policy update, optional skip, reload/reopen, stale-state recovery, dirty draft preservation, and session revocation. Capture actual screenshots/outcomes. Fixture-only browser checks do not prove a live Instagram integration; do not request or log production tokens.
- [ ] **6. Verify disposable backend integration:** pair two clients; save plan/branding and accept consent in one, observe authoritative progress in the other. Attempt a v1 accept after v2 commit and verify 409; confirm scheduler remains gated until required state is ready and plan enabled. If stack prerequisites are unavailable, list exactly which checks remain unverified.
- [ ] **7. Write evidence and README, run `git diff --check`, review against all spec sections, and commit scoped files:** `test(web): verify onboarding acceptance`. Do not push, close issue, or publish PR without user authorization.

## Plan self-review and execution gate

- Tasks 1–2 cover readiness, scheduling gates, inherited and concurrent consent.
- Tasks 3–5 cover branding isolation, safe uploads, backend routes, typed candidates, token error safety, and compatible contract generation.
- Tasks 6–8 cover routing, refresh, manual-token/OAuth flow, all configuration forms, dirty drafts, accessibility, and completion.
- Task 9 covers full regression commands and actual browser/backend acceptance evidence; no fabricated pass claims.
- Names and DTOs are shared through Interfaces blocks; existing generated Kotlin remains compatible even if regeneration is byte-identical.
- This plan changes documentation only. User review and execution-method choice are required before product code changes.
- Recommended execution: Native, because nine tasks share tightly coupled DTOs and session/refresh behavior; keeping these interfaces in one context reduces integration churn. Final independent review remains required by execution workflow.
