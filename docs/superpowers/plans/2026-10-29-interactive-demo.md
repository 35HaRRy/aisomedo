# Interactive Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive demo at `/#/demo/dashboard` that reuses the application UI without accessing real APIs or persisting demo records.

**Architecture:** Resolve demo versus normal mode before mounting session consumers. Route API and live-event requests through a small shared transport backed by one in-memory demo runtime, retaining existing typed API methods and refresh subscriptions. Use memory-only recovery stores and bundled/blob preview URLs to cover paths that do not go through JSON requests.

**Tech Stack:** Existing React, TypeScript, Vite, Vitest, Testing Library, and Playwright; browser Response/ReadableStream and object URLs. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-29-interactive-demo-design.md`

## Global Constraints

- Demo routes live beneath `/#/demo/`. The base route resolves to `/#/demo/dashboard`.
- Display a visible, accessible lowercase **demo** label next to the application logo.
- Changes exist only in memory. They survive navigation between demo screens and reset on page reload. Leaving and reopening the demo starts a new seed state.
- Demo data reads and writes use a mock API layer. No request may fall through to the real API while demo mode is active.
- Every applicable list record type starts with at least two examples. Singleton resources, such as the user profile and settings, have one complete example.
- Removing pairing inside the demo discards the sandbox and opens `/#/welcome`, without changing real pairing state or cookies.
- Documentation is English; questions to the owner remain Turkish. Application notices remain Turkish.
- No backend, worker, database, Android, or deployment changes; no new dependency or Service Worker.
- Preserve existing unsaved-edit guards, input validation, cancellation, conflict handling, and real-session behavior.
- Preserve unrelated user changes. Do not stage or commit unless the owner requests it; commit checkpoints below are optional execution checkpoints, not permission to commit.

## Review Focus

1. Direct demo entry with an old valid authentication cookie but no marker must not probe the real session (Tasks 1, 6, 7).
2. Normal-to-demo navigation while reads or live events are pending must not leak requests or accept old results (Tasks 2, 4, 6).
3. Native media, download, and upload-conflict URLs must not escape the JSON transport boundary (Tasks 5, 7).
4. Unavailable browser storage and StrictMode effect replay must not break startup, persist records, or reset the sandbox mid-navigation (Tasks 1, 3, 6).
5. Editing date-sensitive examples months later must still allow meaningful review/scheduling actions without inventing multiple active packages (Tasks 3, 5).

## File map

New files:

- `web/src/demo/routing.ts`: exact prefix parsing, prefix-aware hrefs, and the real-pairing hint.
- `web/src/demo/runtime.ts`: active sandbox identity, lifetime, in-memory recovery storage, and disposal.
- `web/src/demo/seed.ts`: typed fictional initial state and session-relative timestamps.
- `web/src/demo/api.ts`: method/path handlers, validation, mutation responses, and local resource versions.
- `web/src/api/transport.ts`: capture mode/generation before sending; mock or native transport, never fallback.
- `web/src/demo/assets.ts`: bundled/object URL selection, upload-preview registration, cleanup.
- `web/public/demo/`: small original or already-licensed fictional photo/video sample assets.
- Tests colocated as `routing.test.ts`, `runtime.test.ts`, `api.test.ts`, `assets.test.ts`, `transport.test.ts`, plus `web/src/demo/DemoFlow.test.tsx` and `web/e2e/demo.spec.ts`.

Modify existing integration points, not screen hierarchies:

- `web/src/App.tsx`, `web/src/session.tsx`, `web/src/navigation.ts`, `web/src/live.ts`, `web/src/liveProvider.tsx`.
- `web/src/api/client.ts`, `web/src/api/compat.tsx` (do not manually edit generated `openapi.ts`).
- `web/src/packages/drafts.ts`, `web/src/packages/usePackageEditor.ts`, `web/src/uploads/UploadProvider.tsx`, `web/src/promotion/tourProgress.ts`.
- `web/src/uploads/ConflictControls.tsx`, `web/src/onboarding/InstagramStep.tsx`, `web/src/onboarding/BrandingStep.tsx` where they construct asset URLs or trigger external authorization.
- `web/src/promotion/LandingPage.tsx`, `web/src/styles.css`, `web/src/promotion/promotion.css` for the link, badge, and small simulation notices only.
- Relevant existing tests when a normal-mode regression assertion belongs beside existing behavior.

## Task 1: Define route and real-pairing marker policy

**Files:** Create `web/src/demo/routing.ts`, `web/src/demo/routing.test.ts`, and `web/src/navigation.test.tsx`; modify `web/src/navigation.ts`.

**Interfaces:**

- `isDemoHash(hash: string): boolean` matches `#/demo`, `#/demo/`, and descendants only.
- `normalHref(hash: string): string` removes the prefix, preserves the query, and maps empty demo paths to `#/dashboard`.
- `workspaceHref(href: string, demo: boolean): string` prefixes internal workspace routes once, but leaves `#/welcome` and deliberate normal exits unchanged.
- `readPairingMarker(storage?: Storage | null): boolean` and `writePairingMarker(paired: boolean, storage?: Storage | null): void` use key `aisomedo:real-paired:v1`, value `1`; storage exceptions are nonfatal.

- [ ] Write tests named `matchesOnlyExactDemoSegment`, `preservesReviewOccurrenceAndEncodedFolderQuery`, `normalizesDemoBase`, `doesNotDoublePrefix`, and `blockedStorageMeansNoMarker`. Assert `#/demonstration` is not demo, `#/demo/package?review=7` becomes `#/package?review=7`, and `#/demo/` becomes `#/dashboard`.
- [ ] Run from `web`: `pnpm test src/demo/routing.test.ts`; confirm failures are missing behavior, not setup errors.
- [ ] Implement the interfaces. Make navigation parse the area after removing the demo prefix and construct hrefs consistently for guarded navigation. Unknown demo areas remain inside the demo dashboard.
- [ ] Add navigation tests for guarded Back/Forward and cancelled unsaved-edit navigation retaining `#/demo/`.
- [ ] Run `pnpm test src/demo/routing.test.ts src/navigation.test.tsx src/packages/usePackageEditor.test.tsx`; require all passing.
- [ ] Review the diff as a route-policy checkpoint. No commit without owner authorization.

## Task 2: Establish mode lifetime and fail-closed request transport

**Files:** Create `web/src/demo/runtime.ts`, `web/src/api/transport.ts`, and their test files; modify `web/src/api/client.ts`.

**Interfaces:**

- `DemoRuntime` exposes `readonly generation: number`, `readonly signal: AbortSignal`, `readonly storage: Storage`, `fetch(path: string, init?: RequestInit): Promise<Response>`, and `dispose(): void`.
- `startDemo(): DemoRuntime`, `getDemoRuntime(): DemoRuntime | null`, and `stopDemo(): void` manage one active runtime; repeated `startDemo()` does not reset it.
- `transportFetch(path: string, init?: RequestInit): Promise<Response>` captures mode/runtime at entry. Demo path with no initialized runtime rejects locally; no native fallback. Normal requests use native fetch and reject/abort if their captured generation becomes obsolete.
- The runtime API handler is wired in Task 3. Until then, its fetch rejects unknown operations locally.

- [ ] Write tests `demoNeverCallsNativeFetch`, `uninitializedDemoFailsClosed`, `unknownMockRouteDoesNotFallThrough`, `lateNormalResponseCannotCrossIntoDemo`, and `disposedRuntimeCannotResumeAsRealRequest`. Spy on native fetch and assert zero calls for demo operations, including malformed or unknown paths.
- [ ] Run `pnpm test src/demo/runtime.test.ts src/api/transport.test.ts`; verify red failures.
- [ ] Implement the runtime with a lifetime AbortController, monotonically increasing generation, and minimal memory-backed `Storage`. Capture it before awaiting; dispose aborts operations and clears its owned resources. Avoid initializing/resetting it in React effect cleanup.
- [ ] Route `request()` through `transportFetch` without changing its timeout, version, credential, or ApiError contract. Keep transport modules free of runtime imports from `api/client.ts` to avoid circular initialization.
- [ ] Run `pnpm test src/demo/runtime.test.ts src/api/transport.test.ts src/api/client.test.ts`; require all passing, including existing request cancellation and version checks.
- [ ] Review transport coverage against every native fetch call discovered in the source. No commit without owner authorization.

## Task 3: Implement typed seed data and core mock mutations

**Files:** Create `web/src/demo/seed.ts`, `web/src/demo/api.ts`, `web/src/demo/api.test.ts`; wire `runtime.ts`.

**Interfaces:**

- `createDemoState(now: Date): DemoState` returns typed fields `client`, `setup`, `consent`, `branding`, `plan`, `reminders`, `instagram`, `dashboard`, `editor`, `completed`, `reviews`, `activity`, `uploads`, and `candidates`, based on their corresponding existing OpenAPI resource types. `reviews` is `Map<number, ReviewDetailOut>`; `completed` is `CompletedPackageOut[]`; `uploads` is `Map<string, UploadOut>`; `candidates` uses `AttemptOut["candidates"]`.
- `handleDemoRequest(state: DemoState, path: string, init: RequestInit, signal: AbortSignal): Promise<Response>` returns Response objects with existing JSON/status/error shapes and resource-version headers.
- `DemoState` additionally owns `versions: Map<string, number>` and a listener set for the live stream in Task 4. API handlers increment resource versions after mutations.

- [ ] Write `seedsEveryApplicableCollection`, `seedsOneActivePackage`, and `relativeDatesRemainActionable`. Assert at least two completed packages, media, reviews, occurrences, activity events, and candidate accounts; exactly one active package/profile. Construct seeds at two widely separated dates and assert eligible occurrences/reviews remain coherent.
- [ ] Write `settingsReadAfterWrite`, `packageEditChecksRevision`, `reviewDecisionsAreDistinct`, and `invalidInputDoesNotMutateState`. Assert 409 for stale revisions, 422 for invalid bodies, changed mock state on valid writes, and no completed package for skipped/rescheduled reviews.
- [ ] Run `pnpm test src/demo/api.test.ts`; verify red failures.
- [ ] Implement the seed using existing generated resource types, cloning mutable values. Include truthful singleton setup readiness and fictional connected Instagram status. Do not import test fixtures into production code.
- [ ] Implement handlers for pairing identity, setup/consent, branding/plan/reminders, dashboard/occurrences, active package/editor/edit/remove/restore/clear, completed list/details, review reads/decisions, and activity. Cover every non-upload public method of the existing `api` object; implement media, render, and OAuth completion in Task 5. Use explicit route matching; unknown method/path returns a local error, never generic success.
- [ ] Wire runtime state once per sandbox. Mutation results and later reads must share this state; validate bodies, resource identities, expected folder, and versions before changing it.
- [ ] Run `pnpm test src/demo/api.test.ts src/api/transport.test.ts` and `pnpm typecheck`; require passing. No commit without owner authorization.

## Task 4: Reuse live synchronization without real events or compatibility requests

**Files:** Modify `web/src/live.ts`, `web/src/liveProvider.tsx`, `web/src/api/compat.tsx`, `web/src/demo/api.ts`; extend `web/src/liveProvider.test.tsx`, `web/src/demo/api.test.ts`, and transport tests.

**Interfaces:**

- Existing `LiveCoordinator` and `startLiveRefresh` interfaces remain unchanged. Its default fetcher uses `transportFetch`.
- `GET /api/events` in the mock returns a local `Response` with a `ReadableStream<Uint8Array>`, content type `text/event-stream`, and existing protocol-1 `ready`, `change`, and `heartbeat` frames.
- `GET /api/compat` returns the existing contract version locally; the normal compatibility caller retains current behavior.

- [ ] Write `demoLiveBecomesUsableWithoutNetwork`, `mockMutationRefreshesSubscribers`, `demoHeartbeatDoesNotReconnectToBackend`, and `stoppingDemoClosesStream`. Use fake timers to advance beyond the existing 45-second live deadline and verify zero native fetch calls.
- [ ] Run `pnpm test src/liveProvider.test.tsx src/demo/api.test.ts`; verify the new tests fail before wiring.
- [ ] Implement the local event stream with immediate readiness, change frames using `state.versions`, and heartbeat frames every 15 seconds. Remove listeners and timers on stream cancellation or lifetime abort. This reuses the existing live state machine rather than creating a second coordinator.
- [ ] Make the compatibility caller use the shared transport in demo mode instead of generated `fetchCompat`; do not hand-edit generated code. On mode transitions stop old live ownership, reset request resource versions, and mount fresh consumers before accepting new readiness.
- [ ] Run `pnpm test src/live.test.ts src/liveProvider.test.tsx src/useLiveData.test.ts src/api/transport.test.ts src/demo/api.test.ts`; require passing. No commit without owner authorization.

## Task 5: Complete local upload, preview, render, and Instagram flows

**Files:** Create `web/src/demo/assets.ts`, `web/src/demo/assets.test.ts`, and `web/public/demo/` sample assets; modify `web/src/demo/api.ts`, `web/src/uploads/UploadProvider.tsx`, `web/src/uploads/ConflictControls.tsx`, `web/src/onboarding/InstagramStep.tsx`, `web/src/onboarding/BrandingStep.tsx`; extend mock tests.

**Interfaces:**

- `demoAssetUrl(path: string): string` maps known demo artifact references to bundled `/demo/` assets or runtime-owned blob URLs; unknown references fail locally, never return a real API URL.
- `registerDemoFile(file: File): string` registers a local object URL and returns its opaque runtime reference; bind registration to the current sandbox and revoke its URLs on disposal.
- Keep existing upload transport method signatures. Chunk handlers accept local Blob bodies, validate offsets/declared limits, and update mock UploadOut status without sending bytes anywhere.

- [ ] Write `uploadChunksStayLocal`, `uploadLimitsAndConflictDecisionsAreValidated`, `allPreviewAndDownloadUrlsAreLocal`, `renderUsesSampleNotUserTranscode`, `instagramNeverOpensExternalWindow`, and `disposeRevokesObjectUrls`. Spy on native fetch and `window.open`; assert zero real calls.
- [ ] Run `pnpm test src/demo/assets.test.ts src/demo/api.test.ts`; confirm red failures.
- [ ] Implement upload start/status/range/complete/resolve handlers and registration at file admission in the existing upload transport wrapper. Support local photo/video previews and a deterministic duplicate-filename conflict so conflict controls can be exercised. Use small licensed or original sample assets with valid media metadata.
- [ ] Adapt constructed conflict and branding URLs via the demo asset resolver; audit API-provided preview/download/render URLs too. Preserve real-mode URL construction. Return bundled sample video for render completion, not a fake successful transcode of user bytes.
- [ ] Complete simulated render/retry/publication, manual publish, OAuth start/status/account-selection, and token connection handlers. In the Instagram component branch before `window.open` and external auth-link display: show fictional candidates directly, label the flow simulated, do not solicit real tokens, and clear submitted strings without retaining them.
- [ ] Add Turkish notices: `Demo: işlemler yalnızca bu tarayıcı oturumunda simüle edilir.` and `Örnek önizleme; yüklediğiniz dosya işlenmedi. Gerçek paylaşım yapılmaz.` Keep existing normal-mode copy unchanged.
- [ ] Run `pnpm test src/demo/assets.test.ts src/demo/api.test.ts src/uploads/UploadProvider.test.tsx src/uploads/UploadPanel.test.tsx src/onboarding/BrandingStep.test.tsx src/onboarding/InstagramStep.test.tsx`; require passing. No commit without owner authorization.

## Task 6: Integrate session, UI, and memory-only recovery

**Files:** Modify `web/src/App.tsx`, `web/src/session.tsx`, `web/src/navigation.ts`, `web/src/packages/drafts.ts`, `web/src/packages/usePackageEditor.ts`, `web/src/uploads/UploadProvider.tsx`, `web/src/promotion/tourProgress.ts`, `web/src/promotion/LandingPage.tsx`, and relevant CSS; create `web/src/demo/DemoFlow.test.tsx` and extend existing session/persistence tests.

**Interfaces:**

- The outer App mode gate resolves hash plus marker before mounting session effects. Marker-present demo paths use `history.replaceState` to the equivalent normal href before session restoration; marker-absent paths start the runtime before rendering SessionProvider/ContractBanner.
- Session's public interface remains unchanged. Mock `me` establishes the fictional paired session; real validated `me` sets the marker; confirmed real 401/revocation clears it. Mock operations never change the real marker.
- Existing draft function signatures remain unchanged. Dispatch their operations to a runtime-owned `createDraftStore` built on memory transactions/entries in demo mode, and to IndexedDB otherwise. Capture the selected store at operation entry.
- Upload recovery, remembered-clear state, and tour progress use `getDemoRuntime().storage` while demo is active, and existing storage otherwise. Do not use `storage: null` if it disables normal demo editing/upload actions.

- [ ] Write `directDemoWithCookieAndNoMarkerNeverProbesRealSession`, `markerRedirectsBeforeValidation`, `staleMarker401ClearsOnlyRealHint`, `networkErrorPreservesMarker`, and `demoRevokeOnlyExitsToWelcome`. Assert queries survive redirects and cookies/real saved records remain unchanged.
- [ ] Write `strictModeAndNavigationKeepSandbox`, `reloadOrReentryReseeds`, `blockedStorageStillStartsDemo`, `demoDoesNotOpenIndexedDB`, and `oldReadCannotReplaceDemoIdentity`. Check pending normal read cancellation and transitions using real hashchange events.
- [ ] Run `pnpm test src/demo/DemoFlow.test.tsx src/session.test.tsx`; verify red failures.
- [ ] Implement the outer gate and lifetime cleanup. Do not dispose the sandbox during StrictMode effect replay. Route demo pairing removal to `stopDemo()` and `#/welcome`, without touching real cookies or revocation endpoints. Retain existing dirty-navigation confirmation on exits.
- [ ] Route recovery through memory storage and draft factory seams. Clear runtime-only storage on disposal; never clean real storage by a broad key prefix. Ensure deferred writes capture their old runtime and cannot target IndexedDB after an exit.
- [ ] Add the real `<a href="#/demo/dashboard">Demo</a>` to the welcome header. Add the logo badge, preserve demo prefix for sidebar/setup/walkthrough links, and make the demo setup wizard reachable from settings even though setup starts complete.
- [ ] Run `pnpm test src/demo/DemoFlow.test.tsx src/session.test.tsx src/App.test.tsx src/packages/usePackageEditor.test.tsx src/uploads/UploadProvider.test.tsx src/promotion/tourProgress.test.ts` and `pnpm typecheck`; require passing. No commit without owner authorization.

## Task 7: Prove network isolation in an actual browser and run regressions

**Files:** Create `web/e2e/demo.spec.ts`; update status checkboxes in the approved spec and this plan only after checks actually pass.

**Interfaces:** Use the existing Playwright `web/e2e` configuration and desktop/mobile projects. Do not require a backend or mock API responses in the browser test.

- [ ] Write a browser request recorder before navigation. After `/#/demo/dashboard`, assert no `/api/` request (including absolute same-origin forms) and no workflow-triggered external host request occurs. Bundled app/demo assets and development-server connections are allowed; API response fulfillment must not hide leakage.
- [ ] Add browser cases: welcome header opens demo; setup/settings save survives demo navigation; photo/video previews load; upload-conflict preview stays local; sample rendering and review actions update completed/activity views; downloads target local assets; Instagram simulation opens no popup. Use stable accessible locators, not fixed sleeps.
- [ ] Add reload/reset, real-record preservation, marker redirect/query retention, and badge checks in both desktop and mobile projects. Test stale-cookie/no-marker demo without probing real `me`. Marker redirect tests may observe or intentionally fulfill normal API only after asserting the URL has left demo mode; keep those separate from isolation tests.
- [ ] Run from `web`: `pnpm test:browser e2e/demo.spec.ts`; inspect failures, implement only missing integration behavior, rerun until both projects pass.
- [ ] Run from `web`: `pnpm test`, then `pnpm typecheck`, then `pnpm build`, then `pnpm test:browser`. Require exit code zero for each. If a failure predates this work, reproduce against the unchanged relevant code and report it rather than claiming an all-green result.
- [ ] Run `git diff --check` and `git status --short`; inspect the scoped diff, confirm unrelated files remain untouched, and report the exact verification results. Do not stage or commit without owner authorization.

## Self-review and handoff

- [x] Every agreed requirement maps to a task: routing/marker (1, 6), no-network boundary (2, 4, 5, 7), seed counts (3), mutations and simulated effects (3, 5), memory lifecycle (2, 6), UI entry/badge (6), and regression checks (7).
- [x] All five review-focus risks have explicit named tests in their owning tasks.
- [x] Task interfaces reuse existing API and live contracts; the generated contract remains unchanged.
- [x] No product dependency, separate screen hierarchy, or backend change is planned.
- [x] Owner reviews this plan and selects native execution in the existing checkout.

Recommended execution: **native, in this session**, because route, runtime, and session isolation share tightly coupled interfaces and benefit from one implementer's continuous context. Request an independent whole-diff review after implementation rather than paying for a fresh implementation/review context per task. Execution remains gated on the owner's plan review and method selection.

## Execution result

- [x] Task 1: route and pairing-marker policy.
- [x] Task 2: runtime lifetime and fail-closed transport.
- [x] Task 3: typed seed data and mock mutations.
- [x] Task 4: local live synchronization and compatibility.
- [x] Task 5: local media, rendering, and Instagram simulation.
- [x] Task 6: session/UI integration and memory-only recovery.
- [x] Task 7: desktop/mobile isolation acceptance and full regressions.
- [x] Independent final review and one verified fix pass.

Final verification: 469 unit/integration tests passed; full browser suite 93 passed and 1 skipped; production build and diff whitespace check passed. Tests for transport and generation fencing live beside runtime tests rather than in a duplicate transport-only suite. Detailed implementation decisions and compatibility notes are recorded in the spec's implementation notes. No commits, staging, merge, or push were performed.
