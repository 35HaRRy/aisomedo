# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #25: paired, responsive Turkish web shell with authoritative dashboard status and five-second foreground refresh.

**Architecture:** A read-only domain summary feeds one authenticated dashboard endpoint. A cookie-authenticated browser refresh controller drives the shell; worker status comes from the existing progress record through a shared read-only mount. Browser DTOs are generated from OpenAPI.

**Tech Stack:** Existing React 18/TypeScript/Vite, FastAPI/Pydantic, Python 3.12, dojo-core, pytest; add Vitest, jsdom, and Testing Library for behavioral web tests, using versions compatible with the existing Vite and React versions.

**Spec:** `docs/superpowers/specs/2026-09-30-web-dashboard-design.md` (user approved).

## Global Constraints

- The user explicitly accepted a five-second refresh interval.
- The endpoint is a read model, not a scheduler trigger.
- Credentials remain in HttpOnly cookies; browser storage does not hold tokens.
- All authored user-facing strings live in a Turkish locale catalog.
- Dates display in `Europe/Istanbul` using Turkish formatting.
- Worker idle expires after 120 seconds and busy after 3600 seconds by default.
- Regenerate OpenAPI and both committed client artifacts for contract changes.
- Rich upload, review-resolution, and settings-editing workflows belong to #26–#31.
- Keep existing compatibility checks and same-origin deployment behavior.

## Review Focus

- Old requests completing after revocation/re-pairing must not restore protected data (Task 4).
- A future regular row from an obsolete plan must not override the current plan or a replacement one-off (Task 1).
- A stuck busy worker must expire even while the API stays healthy (Task 2).
- Slow or failed optional health sources must not erase package/review status (Task 3).
- Unknown activity/status codes and long Turkish names must render safely without untranslated raw errors or horizontal overflow (Tasks 5–6).

## File responsibilities

- `dojo-core/src/dojo/dashboard.py`: typed read-model values and pure next-slot selection.
- `dojo-core/src/dojo/publishing.py`: public summary method using existing stores and clock.
- `dojo-core/src/dojo/worker_health.py`: shared progress-record validation and status value.
- `worker/src/worker/health.py`: existing writer/CLI, delegating validation to shared utility.
- `backend/src/backend/routes/dashboard.py`: authenticated aggregation and response schemas.
- `backend/scripts/generate_clients.py`: schema-driven TypeScript DTO output, preserving existing exports.
- `web/src/api/client.ts`: relative-path HTTP requests and structured transport errors.
- `web/src/session.tsx`: session restoration, pairing, invalidation boundary.
- `web/src/live.ts`: visibility-aware, single-flight refresh controller.
- `web/src/i18n/{tr.ts,index.ts}`: text catalog and date/status formatting.
- `web/src/{App.tsx,navigation.ts,styles.css}` and `web/src/components/*.tsx`: shell and summary views.
- `ops/docker-compose{,.prod}.yml`: shared worker-health mount and configuration.

## Task 1: Read-only domain dashboard summary

**Files:** Create `dojo-core/src/dojo/dashboard.py`, `dojo-core/tests/test_dashboard.py`; modify `dojo-core/src/dojo/publishing.py`, `dojo-core/src/dojo/__init__.py`.

**Interfaces:**
- Consumes existing `SchedulePlan`, `YayinZamani`, `YayinIncelemesi`, `Package`, public store operations, and injected clock.
- Produces `DojoPublishing.get_dashboard_summary() -> PublishingDashboard`.
- Frozen dataclasses in `dashboard.py`: `NextSlot(kind: str, due_at: datetime)`, `PendingAction(occurrence_id: int, review_id: int | None, version: int | None, due_at: datetime, package_folder: str | None, state: Literal["review_ready", "empty_package", "preparing"])`, `PublishingDashboard(generated_at: datetime, package: Package | None, next_slot: NextSlot | None, pending_actions: list[PendingAction], plan: SchedulePlan)`.
- Pure `next_slot(plan: SchedulePlan, occurrences: list[YayinZamani], now: datetime) -> NextSlot | None`.

- [ ] **1. Write behavior tests** using `FakeClock` and existing seam fixtures. Pin: absent package returns `package is None`; repeated reads leave observable package list, audit, pending reviews, and scheduled occurrences unchanged. Publication-in-progress returns the publishing package. Pending reviews retain IDs/versions; resolved reviews disappear; overdue slots with no review become preparing/empty actions without creating reviews.
- [ ] **2. Add schedule assertions:** anchor `2026-08-03 10:00 Europe/Istanbul`, now exactly that time => next regular `2026-08-17 10:00`; pending one-off `2026-08-04 12:00` wins; resolved one-off excluded; disabled plan emits no regular candidate; plan changes ignore obsolete regular rows. Future manual candidates participate; overdue candidates remain pending actions. Multiple pending reviews remain visible.
- [ ] **3. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_dashboard.py -v`; confirm missing-summary failures.
- [ ] **4. Implement public summary.** Reuse read-only package/manifest/publication facts and store reads; never call `get_or_create_active_package`, `ensure_schedule_upto`, or render/preview methods. Compute recurrence arithmetically from the current anchor with 14-day spacing, strictly after now. Skip resolved matching regular dates; include only pending manual/oneoff future rows. Join due occurrences and pending reviews by occurrence ID; preserve orphan pending reviews with creation time as due-time fallback. Classify empty from selected montage media; preparing from absence of a current ready render; otherwise review-ready. Read the publishing package when no active package exists. Export summary types through `dojo`.
- [ ] **5. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_dashboard.py dojo-core/tests/test_schedule.py dojo-core/tests/test_review.py dojo-core/tests/test_review_resolution.py -v`; expected PASS. Add a PostgreSQL-backed summary case using existing integration fixtures to prove persisted exceptions are honored.
- [ ] **6. Commit task:** `feat(core): expose read-only dashboard summary`.

## Task 2: Shared worker-health observation

**Files:** Create `dojo-core/src/dojo/worker_health.py`, `dojo-core/tests/test_worker_health.py`; modify `worker/src/worker/health.py`, `worker/tests/test_health.py`, `ops/docker-compose.yml`, `ops/docker-compose.prod.yml`, `ops/.env.example`, `README.md`.

**Interfaces:**
- Produces `WorkerStatus(status: Literal["healthy", "unhealthy", "unknown"], phase: Literal["idle", "busy", "stopped"] | None)`.
- Produces `read_worker_status(path: Path | None) -> WorkerStatus` and shared `current_boot_id() -> str`.
- Preserves `WorkerHealth`, `check_health(path: Path) -> bool`, and `python -m worker.health` behavior.

- [ ] **1. Write tests:** missing/unconfigured => unknown; idle at elapsed 119 seconds => healthy, 120 => unhealthy; busy at 121 => healthy, 3600 => unhealthy. Corrupt JSON, malformed numbers, boolean timestamps, future written time, stopped, wrong boot, and unsupported version => unhealthy. A busy record's deadline is not extended by repeated `busy()` calls. Existing CLI exits nonzero for unknown/unhealthy.
- [ ] **2. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_worker_health.py -v`; expect missing shared reader failure.
- [ ] **3. Extract validation** without changing writer's atomic replacement or deadlines. Shared status contains no filesystem path or raw exception. Update worker tests to control time/boot identity at the owning module rather than relying on relocated imports.
- [ ] **4. Wire deployment:** mount named `worker-health` at `/run/dojo-worker` writable for worker and read-only for backend in both standalone Compose bases. Set both `WORKER_HEALTH_PATH` defaults to `/run/dojo-worker/health.json`; preserve timeout overrides. Update `.env.example` and README to require overridden container paths inside this mount and document upgrade from the old `/tmp` path. Standalone non-container worker default may remain `/tmp/dojo-worker-health.json`.
- [ ] **5. Run:** `uv run --project dojo-core pytest dojo-core/tests/test_worker_health.py -v` and `uv run --project worker pytest worker/tests/test_health.py -v`; expected PASS. Render each Compose combination with `ops/.env.example`; verify identical record paths and backend read-only mount. Commands listed in Task 6.
- [ ] **6. Commit task:** `feat(ops): expose worker progress to dashboard`.

## Task 3: Authenticated dashboard contract and generated browser types

**Files:** Create `backend/src/backend/routes/dashboard.py`, `backend/tests/test_dashboard_api.py`, `backend/tests/test_client_generation.py`; modify `backend/src/backend/main.py`, `backend/scripts/generate_clients.py`, `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`.

**Interfaces:**
- Consumes Tasks 1–2, existing `get_current_client`, existing Meta status interface.
- Produces `GET /api/dashboard -> DashboardOut`: `generated_at`, `package`, `next_slot`, `pending_actions`, `plan`, `instagram`, `worker`.
- Pydantic schemas: `DashboardOut`, `DashboardSlotOut`, `DashboardActionOut`, `DashboardInstagramOut(health: str, username: str | None)`, `DashboardWorkerOut(status: Literal["healthy", "unhealthy", "unknown"], phase: Literal["idle", "busy", "stopped"] | None)`; reuse `PackageOut` and `PlanOut`.
- Generated TypeScript exports use these exact schema names plus `ClientOut`, `ValidateIn`, `ActivityPageOut`, `ActivityEventOut`, `ClientRefOut`, and transitive references. Existing `CompatInfo`, `fetchCompat`, `CONTRACT_VERSION`, `API_PATHS` remain supported.

- [ ] **1. Write API tests:** unpaired/revoked => 401; paired browser => 200 typed response, `Cache-Control: no-store`; absent package => null without creation; publishing package stays visible; no Meta configuration => disconnected; failing Meta => unknown while package/actions remain; missing worker file => unknown; expired busy => unhealthy despite healthy API. Assert no credential/provider exception appears anywhere in body.
- [ ] **2. Run:** `uv run --project backend pytest backend/tests/test_dashboard_api.py -v`; expected missing route failure.
- [ ] **3. Implement aggregation.** Read cached/persisted Meta connection state, never perform remote refresh during dashboard GET. Missing/failed optional health sources return explicit safe fallback. Core summary failure remains an HTTP failure, not fabricated empty data. Register router with authentication dependency; use configured worker path and injectable health reader for tests.
- [ ] **4. Write generator tests:** alter a schema property and assert output follows it; verify `$ref`, required/optional fields, nullable unions, literal enums, arrays, and object dictionaries. Reject unsupported schema constructs used by selected DTOs instead of silently emitting incorrect types. Run `uv run --project backend pytest backend/tests/test_client_generation.py -v`; confirm failure before changes.
- [ ] **5. Extend deterministic generator** to traverse selected schema components and their references. Generate DTOs from properties, not hardcoded dashboard strings. Preserve current Kotlin compatibility exports; regenerate its artifact along with TypeScript. No Android dashboard feature is introduced.
- [ ] **6. Run:** `uv run --project backend python backend/scripts/export_openapi.py`, then `uv run --project backend python backend/scripts/generate_clients.py`, then `uv run --project backend pytest backend/tests/test_dashboard_api.py backend/tests/test_client_generation.py backend/tests/test_contract.py -v`; expected PASS. Run `npm run typecheck` in `web`.
- [ ] **7. Commit task:** `feat(api): add typed dashboard snapshot`.

## Task 4: Browser session and single-flight refresh controller

**Files:** Create `web/src/api/client.ts`, `web/src/api/client.test.ts`, `web/src/session.tsx`, `web/src/session.test.tsx`, `web/src/live.ts`, `web/src/live.test.ts`, `web/src/test/setup.ts`, `web/vitest.config.ts`; modify `web/package.json`, `web/package-lock.json`.

**Interfaces:**
- Consumes Task 3 generated DTOs.
- Produces `ApiError` with `status: number` and `request<T>(path: string, init?: RequestInit): Promise<T>` using same-origin credentials and bounded 10-second timeout; supplied abort signals remain effective.
- `api.me(signal?: AbortSignal): Promise<ClientOut>`, `api.pair(body: ValidateIn, signal?: AbortSignal): Promise<void>`, `api.dashboard(signal?: AbortSignal): Promise<DashboardOut>`, `api.activity(signal?: AbortSignal): Promise<ActivityPageOut>` (limit 20).
- `SessionProvider`/`useSession()` expose `status: "loading" | "paired" | "unpaired" | "error"`, `client: ClientOut | null`, `generation: number`, `restore(): Promise<void>`, `pair(code: string, name: string): Promise<void>`, `invalidate(): void`.
- `startLiveRefresh(refresh: (signal: AbortSignal) => Promise<void>, environment?: LiveEnvironment): () => void`; environment supplies clock/event targets/visibility/connectivity for tests. First call immediate; cadence 5000ms; cleanup aborts in-flight request and detaches listeners.

- [ ] **1. Add test harness** with `test: vitest run`, jsdom, Testing Library cleanup and jest-dom; choose compatible dependency releases after checking current docs during implementation. Keep npm as CI's authoritative lockfile workflow; inspect existing pnpm artifacts before any changes.
- [ ] **2. Write session/client tests:** successful cookie-based restoration and pairing (`kind === "browser"`); structured 401/429/network/timeout outcomes; invalid code does not become paired; server failure becomes retryable error; no token storage; aborted or old-generation responses never publish session data. Run `npm test -- src/api/client.test.ts src/session.test.tsx`; expect missing-module failures.
- [ ] **3. Implement client/session boundary.** Pairing returns void because existing endpoint returns an untyped response; recheck `/me` after success. Invalidation synchronously clears client data and increments generation. Only protected 401 invalidates session; pairing validation 401 stays a form error.
- [ ] **4. Write deterministic refresh tests:** immediate request; no second request before 5000ms; due-review addition/resolution visible on next tick; hidden/offline pause; focus/online/visibility events coalesce; slow request never overlaps; failure permits next tick; cleanup aborts and prevents callbacks; obsolete generation is ignored by caller. Run `npm test -- src/live.test.ts`; expect failure.
- [ ] **5. Implement controller** with one active AbortController and one cadence timer. Skip busy ticks; focus/reconnect requests one deferred immediate refresh if busy. Hiding aborts current request; no background refresh. Treat abort as cancellation rather than user-facing network error.
- [ ] **6. Run:** `npm test -- src/api/client.test.ts src/session.test.tsx src/live.test.ts` and `npm run typecheck`; expected PASS.
- [ ] **7. Commit task:** `feat(web): add session and live refresh lifecycle`.

## Task 5: Turkish responsive shell and summary destinations

**Files:** Create `web/src/i18n/tr.ts`, `web/src/i18n/index.ts`, `web/src/navigation.ts`, `web/src/styles.css`, `web/src/components/PairingForm.tsx`, `web/src/components/Dashboard.tsx`, `web/src/components/PackageSummary.tsx`, `web/src/components/ActivitySummary.tsx`, `web/src/components/SettingsSummary.tsx`, `web/src/App.test.tsx`; modify `web/src/App.tsx`, `web/src/main.tsx`, `web/src/api/compat.tsx`, `web/index.html`.

**Interfaces:**
- Consumes Tasks 3–4.
- `useNavigation(): { area: "dashboard" | "package" | "activity" | "settings"; reviewId: number | null }`; hashes `#/dashboard`, `#/package`, `#/package?review=<id>`, `#/activity`, `#/settings`; invalid hash defaults to dashboard.
- Components: `PairingForm()` uses session context; `Dashboard({data}: {data: DashboardOut})`; `PackageSummary({data, reviewId}: {data: DashboardOut; reviewId: number | null})`; `ActivitySummary({data}: {data: ActivityPageOut})`; `SettingsSummary({data, client}: {data: DashboardOut; client: ClientOut})`.
- `tr` is typed Turkish catalog; `formatDate(value: string): string` uses `tr-TR`, `Europe/Istanbul`; status/action mappings use translated fallback for unknown codes.

- [ ] **1. Write UI tests:** neutral loading, failed-session retry, successful pairing, invalid-code and throttling copy, submit disabled while pending, four labelled navigation destinations and back/forward behavior. Dashboard renders all five categories and Istanbul date. Empty and publishing states differ. Pending-review link selects summary; externally resolved review shows localized handled/unavailable state.
- [ ] **2. Add failure tests:** transient dashboard failure retains last good data with stale label and last success time; first failure shows retry instead of invented values; 401 clears all protected content; late response after re-pair cannot restore old package. Activity failure has independent retry/stale state and does not hide dashboard. Unknown action/status uses translated generic text. Run `npm test -- src/App.test.tsx`; confirm failures.
- [ ] **3. Implement shell and pages.** Wrap app in session provider. Refresh dashboard across all paired areas; refresh activity only when its area is visible, with its own error state. Cancel obsolete route/session work. Reuse snapshot plan/Instagram for settings and snapshot package/actions for package view. Show actor, translated event action, and date for recent activity; do not dump raw event details. Render all text safely through React.
- [ ] **4. Implement localization and styling:** `html lang="tr"`; labels `Kontrol Paneli`, `Güncel Paket`, `Etkinlik`, `Ayarlar`; move compatibility banner text into catalog. Single light theme, neutral background, dark readable text, one restrained accent; status meaning always includes text. Desktop sidebar and mobile compact nav, stacked status sections at narrow widths, wrapping long names, visible keyboard focus, semantic alerts and labelled fields. Keep recurring refresh announcements quiet; announce errors and important review-state changes rather than every poll.
- [ ] **5. Run:** `npm test`, `npm run typecheck`, `npm run build` in `web`; expected PASS. Verify tests query roles/text rather than component internals.
- [ ] **6. Commit task:** `feat(web): build Turkish dashboard shell`.

## Task 6: Integration checks, CI, and browser acceptance

**Files:** Modify `.github/workflows/ci.yml`, `README.md`; create `docs/verification/issue-25-web-dashboard.md`; adjust earlier files only for demonstrated defects.

**Interfaces:** Consumes the complete app; produces reproducible verification instructions and CI execution of `npm test` before web build.

- [ ] **1. Add web test command to CI** and document pairing bootstrap, foreground polling, health-volume setup, and summary-only destination scope. Add verification checklist for each issue acceptance criterion.
- [ ] **2. Run web checks:** `npm ci`, `npm test`, `npm run build` from `web`; expect passing tests and production bundle.
- [ ] **3. Run relevant Python suites separately:** `uv run --project dojo-core pytest dojo-core/tests/test_dashboard.py dojo-core/tests/test_worker_health.py dojo-core/tests/test_schedule.py dojo-core/tests/test_review.py dojo-core/tests/test_review_resolution.py -v`; `uv run --project backend pytest backend/tests/test_dashboard_api.py backend/tests/test_client_generation.py backend/tests/test_contract.py backend/tests/test_api.py -v`; `uv run --project worker pytest worker/tests/test_health.py -v`. Run existing lint/typecheck commands from CI for modified Python packages. Record baseline failures separately from introduced failures.
- [ ] **4. Check schema drift:** rerun export and generation commands from Task 3, then `git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`; expected no changes after committed generation.
- [ ] **5. Render deployment configurations:** `docker compose --env-file ops/.env.example -f ops/docker-compose.yml config`; `docker compose --env-file ops/.env.example -f ops/docker-compose.prod.yml -f ops/docker-compose.dedicated.yml config`; repeat production command with `ops/docker-compose.existing-proxy.yml` instead of dedicated. Expect valid config and shared health path with read-only backend mount. Run existing monitoring-override CI render procedure as well.
- [ ] **6. Browser acceptance:** use browser tooling against a local test deployment with disposable data. Pair two browser contexts; drive due-review creation and resolution through existing backend/worker test setup, observe refresh in the other browser without navigation. Revoke one browser and confirm protected content clears on next request. Check 320px, 390px, and 1280px viewports, long Turkish names, keyboard-only pairing/navigation, hash reload/back, offline/stale recovery, unknown-worker state, and no horizontal overflow. Capture screenshots and actual outcomes in verification document. If environment prerequisites block real deployment, report exactly which checks remain unverified; mocked UI tests do not count as deployed acceptance.
- [ ] **7. Run `git diff --check`**, review final diff against spec, and commit `test(web): verify dashboard acceptance and CI`. Summarize evidence and remaining blockers; do not close #25 unless acceptance criteria have been demonstrated.

## Plan self-review

- Spec requirements map to Tasks 1–6; schedule and package reads stay behind the domain seam.
- Shared interfaces use one DTO vocabulary; generated browser types are schema-derived.
- Session races, schedule exceptions, fixed worker deadlines, partial failures, and unknown UI data have explicit tests.
- No product code or dependency changes are part of this planning stage.
- Execution method awaits user selection after plan review.
