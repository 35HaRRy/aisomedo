# Android Offline Cache and Update Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement #37: durable offline package/Activity reads, guarded mutations, reconnect-safe uploads, and a persistent unsupported-version gate.

**Architecture:** One private JSON snapshot holds authoritative read data and update state; one application-owned network monitor feeds existing model/upload infrastructure. Extend current mutation boundaries and constrained schedulers, rather than queueing offline commands or introducing a database.

**Tech Stack:** Kotlin, Compose, kotlinx.serialization/coroutines, OkHttp/MockWebServer, existing JUnit and Android instrumentation, existing Python OpenAPI generator.

**Spec:** `docs/superpowers/specs/2026-10-12-android-offline-cache-update-design.md`

## Global Constraints

- Android 10/API 29 minimum; preserve pre-34 WorkManager and API 34+ UIDT adapters.
- No database, new product dependency, offline mutation queue, or backend redesign.
- Cache limit: 4 MiB; latest-50-events Activity slice; metadata only, not media bytes.
- Externalized Turkish strings; existing four destinations, adaptive layout, accessibility.
- Only existing-transfer pause/resume changes are allowed offline; local server change may clear session/cache.
- Full Activity browsing/settings remain #38; review implementation remains #36.
- Preserve session/revision fences; credentials, drafts, commands, previews stay outside read cache.
- Run device tests only on dedicated test installations; unrun acceptance remains unverified.
- Leave `android/app/google-services.json` and `ops/fcm_credentials.json` untouched and unstaged.

## Review Focus

- Default-network handover followed by an obsolete loss callback must not mark the replacement disconnected (Task 3).
- Successful dashboard read for a replacement package plus failed editor read must not display the old package editor (Task 4).
- Permission/document-picker result delivered after disconnect must not enqueue or replace a file (Tasks 5–6).
- Background HTTP 426 without a visible Activity must persist the update gate before scheduling another run (Task 5).
- Snapshot write failure after an acknowledged server write must report cache failure, not invite command replay (Task 4).

---

## File ownership and execution order

Paths below are repository-relative. Execute in order; interfaces are shared, so
parallel implementation provides little benefit.

- Activity contracts: `backend/scripts/generate_clients.py`, generated Android DTOs, `api/DojoApi.kt`.
- Read persistence: new `android/app/src/main/java/com/dojo/aisomedo/offline/SnapshotStore.kt`.
- Platform signal: new `android/app/src/main/java/com/dojo/aisomedo/offline/NetworkMonitor.kt`.
- Startup, freshness, and foreground writes: existing `AppViewModel.kt`, wired by `MainActivity.kt`.
- Transfer state and background update failures: existing `uploads/UploadRuntime.kt`, `UploadEngine.kt`, and jobs only if their cancellation/rescheduling contract needs adjustment.
- Presentation: existing `ui/` and `onboarding/` components; new small `ui/ActivityScreen.kt`.

Keep new classes in these responsibility-based files. Do not split or rewrite the
existing ViewModel as an unrelated refactor. Test additions extend current fixtures.

### Task 1: Consume the existing Activity wire contract

**Files:** Modify `backend/scripts/generate_clients.py`, `backend/tests/test_client_generation.py`, `android/app/src/main/java/com/dojo/aisomedo/api/DojoApi.kt`, generated `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`, and `android/app/src/test/java/com/dojo/aisomedo/api/DojoApiTest.kt`.

**Interfaces:** Produces `suspend fun DojoApi.activity(): ActivityPageOut`; generated `ActivityPageOut(events: List<ActivityEventOut>, nextCursor: Int?)`, with `ActivityEventOut.actor: JsonElement`, `details: Map<String, JsonElement>`, and generated `ClientRefOut`.

- [ ] **1. Write failing generation/transport checks.** Add `test_android_activity_generation_preserves_actor_union`: run `main()` into temporary targets and assert `"data class ActivityPageOut("`, `"val actor: JsonElement"`, and `"data class ClientRefOut("` occur. Keep `test_kotlin_rejects_unsupported_shapes` passing. In `DojoApiTest.activityUsesAuthenticatedLatest50AndBothActorShapes`, serve string and client-object actors and assert `request.path == "/api/activity?limit=50"`, bearer/version headers unchanged, two events decoded, `nextCursor == null`, and actor JSON roundtrips unchanged.
- [ ] **2. Verify red.** Run `uv run --project backend pytest backend/tests/test_client_generation.py -q` and `./android/gradlew.bat -p android :app:testDebugUnitTest --tests '*DojoApiTest*'`. Expect the new generation assertion and missing Activity API to fail, not toolchain failures.
- [ ] **3. Implement minimal contract support.** Add `ActivityPageOut` to Kotlin roots. Support only the exact `ClientRefOut`/string `anyOf` shape using `JsonElement`, enqueueing the referenced DTO; keep unrelated heterogeneous unions rejected. Add `activity()` using current authenticated request/decode. Leave `uploadWasSkipped()` and its authoritative audit pagination unchanged.
- [ ] **4. Verify green and reproducibility.** Run both commands above, then `uv run --project backend python backend/scripts/generate_clients.py` twice. Second run must produce identical output; backend OpenAPI and web DTOs must remain unchanged.
- [ ] **5. Commit only Task 1 paths.** `git commit -m "feat(android): consume recent activity contract"` after explicit-path staging and `git diff --cached --check`.

### Task 2: Add bounded, atomic, identity-scoped read storage

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/offline/SnapshotStore.kt` and `android/app/src/test/java/com/dojo/aisomedo/offline/SnapshotStoreTest.kt`.

**Interfaces:** Produces serializable `CachedSnapshot(schemaVersion: Int = 1, origin: String, compat: CompatInfo? = null, updateUrl: String? = null, rejectedVersionCode: Int? = null, data: CachedContent? = null)` and `CachedContent(bindingId: String, client: ClientOut, setup: SetupOut, dashboard: DashboardOut? = null, editor: ActiveEditorOut? = null, activity: ActivityPageOut? = null, dashboardFetchedAt: Long? = null, editorFetchedAt: Long? = null, activityFetchedAt: Long? = null)`.

`SnapshotStore(directory: File)` exposes synchronized `read(origin: String, bindingId: String?): CachedSnapshot?`, `update(origin: String, change: (CachedSnapshot) -> CachedSnapshot): CachedSnapshot`, and `clear(): Unit`. `read` returns only matching-origin update information, with `data` omitted for absent/mismatched binding. `update` starts a fresh envelope for an absent/mismatched origin and throws on storage failure. Constant `MAX_BYTES = 4 * 1024 * 1024`.

- [ ] **1. Write failing storage checks.** Tests `roundtripDoesNotPersistDraftsOrCredentials`, `mismatchedBindingKeepsOnlyOriginScopedUpdate`, `invalidFilesAreMisses`, `failedReplacementPreservesPriorSnapshot`, and `successfulEmptyReadIsNotMissing` assert full DTO roundtrip; foreign-origin read is null; foreign-binding `data == null`; unpaired safe update URL survives; empty Activity has non-null fetch time; missing Activity has null fetch time. Assert corrupt JSON, schema 2, invalid binding/timestamp, and `MAX_BYTES + 1` file return null. Simulate serialization/size failure and assert old file bytes remain identical.
- [ ] **2. Verify red.** Run `./android/gradlew.bat -p android :app:testDebugUnitTest --tests '*SnapshotStoreTest*'`; expect missing store/types.
- [ ] **3. Implement storage.** Reuse atomic temp-write/sync/move pattern from `SessionStore`/`UploadStore`, not their credential files. Validate normalized origin, positive device identity, 64-character lowercase hex binding, nonnegative timestamps, at most 50 events, and safe external URL. Non-null sections require timestamps; null editor plus non-null editor timestamp represents a successful absent-package read. Bound input before reading and serialized output before replacing. Cache parse/validation errors are misses; disk-write errors propagate. One `snapshot.json` and its owned temporary file; no directory-wide deletion.
- [ ] **4. Verify green.** Run the Task 2 command; all storage assertions pass. Mark 4 MiB ceiling with a `ponytail:` comment naming expansion/streaming as the upgrade path.
- [ ] **5. Commit Task 2 paths.** `git commit -m "feat(android): persist bounded read snapshots"`.

### Task 3: Own connectivity independently of Activity lifetime

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/offline/NetworkMonitor.kt`, `android/app/src/test/java/com/dojo/aisomedo/offline/NetworkMonitorTest.kt`, and `android/app/src/androidTest/java/com/dojo/aisomedo/offline/NetworkMonitorAndroidTest.kt`; modify `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadRuntime.kt`.

**Interfaces:** Produces `NetworkStatus(connected: Boolean = false, epoch: Long = 0)`, `NetworkMonitor(context: Context)` with `val state: StateFlow<NetworkStatus>` and `close(): Unit`. Same-file internal `NetworkTracker` owns `state` plus `available(key: Any)`, `capabilities(key: Any, internet: Boolean, validated: Boolean)`, and `lost(key: Any)` for deterministic tests. Runtime owns one `val network: NetworkMonitor`, initialized from application context.

- [ ] **1. Write failing callback-state checks.** `handoverIgnoresObsoleteLoss`: announce A, validate A, announce/validate B, then lose A; `assertTrue(tracker.state.value.connected)`. `availableAloneCannotEnableNetwork`: available without validated capabilities stays false. `lossAndRevalidationAdvanceEpoch`: actual loss/reconnect increments epoch; duplicate capabilities do not. Instrumentation `closeUnregistersAndRecreationReusesRuntimeMonitor` asserts explicit test monitor disposal unregisters and repeated `UploadRuntime.get(context).network` is the same instance.
- [ ] **2. Verify red.** Run `./android/gradlew.bat -p android :app:testDebugUnitTest --tests '*NetworkMonitorTest*'`; expect missing monitor/tracker.
- [ ] **3. Implement native adapter and tracker.** Register one `ConnectivityManager.registerDefaultNetworkCallback`; require INTERNET and VALIDATED in supplied capabilities for `connected`. Track network identity, invalidate on replacement, and ignore old-network callbacks. Use supplied callback capabilities rather than synchronous capability lookup in `onAvailable`. Safely reconcile initial state without overwriting newer callbacks. Callback registration failure is unavailable, not online. `close()` unregisters; production monitor lives with runtime, not Activity. Tests/local fixtures inject state instead of relying on public-internet validation.
- [ ] **4. Verify green/compile.** Run Task 3 unit command and `./android/gradlew.bat -p android :app:assembleDebugAndroidTest`; execute the instrumentation class only on a dedicated emulator when available.
- [ ] **5. Commit Task 3 paths.** `git commit -m "feat(android): observe application connectivity"`.

Reference: [Android network-state guide](https://developer.android.com/develop/connectivity/network-ops/reading-network-state), checked 2026-10-12. Callback state is not proof of backend reachability.

### Task 4: Restore cached views, enforce freshness, persist update gate

**Files:** Modify `android/app/src/main/java/com/dojo/aisomedo/AppViewModel.kt`, `MainActivity.kt`, and `android/app/src/test/java/com/dojo/aisomedo/AppViewModelTest.kt`; create `android/app/src/test/java/com/dojo/aisomedo/OfflineAppViewModelTest.kt`.

**Interfaces:** Add constructor inputs before final `onSessionStopped` callback: `snapshots: SnapshotStore? = null`, `network: StateFlow<NetworkStatus> = MutableStateFlow(NetworkStatus(true))`, and `now: () -> Long = System::currentTimeMillis`. Preserve existing trailing-lambda calls; update MainActivity's positional callback to named argument. Production passes runtime-owned store/monitor (Task 5 creates store property).

Add `AppUiState.networkConnected: Boolean`, `authoritative: Boolean`, `configurationFresh: Set<String>`, `activity: ActivityPageOut?`, and the three nullable fetched timestamps from Task 2. Computed `canMutate: Boolean` requires READY, connected, authoritative, and not busy. `canEditMedia` additionally requires fresh editor, matching dashboard package, and current editor protections. Configuration mutation/draft inputs also require their step in `configurationFresh`. Expose `AppViewModel.currentBinding: String?` read-only for runtime access binding; never expose token.

- [ ] **1. Write failing model cases.** Extend existing fixture with Activity responses and coherent dashboard/editor package fixtures. In new same-package test class reuse existing coroutine/MockWebServer pattern, adding durable directory, AES key, restartable model owner, injected `MutableStateFlow<NetworkStatus>`, and clock. Cases/assertions:
  - `coldOfflineStartRestoresHistoricalSections`: `phase == READY`, package and Activity equal persisted values, timestamps unchanged, `canMutate == false`, `server.requestCount == 0`.
  - `offlineMissAndEmptyHistoryDiffer`: no snapshot stays unavailable; cached empty page remains distinguishable by timestamp.
  - `disconnectBlocksDirectWritesAndPreservesDrafts`: call existing config/consent/OAuth/media entry points and draft mutators; request count and drafts remain unchanged.
  - `reconnectWaitsForFreshResourceReads`: with editor/config failures, shared state recovers only after startup checks; affected resource predicates stay false; another successful section retains its data.
  - `replacementPackageInvalidatesOldEditor` and `delayedOldSessionCannotCommitCache`: old editor absent and new session snapshot untouched after delayed response.
  - `cacheWriteFailureAfterAcceptedWriteDoesNotReplay`: server mutation count is exactly 1, authoritative response handled, storage issue shown, subsequent refresh sends reads only.
  - `unsupportedStateSurvivesRestartAndFailedRefresh`: foreground 426/minimum retains UPDATE_REQUIRED offline; missing URL does not drop gate; new installed code re-evaluates; 401 removes protected content; unpaired minimum gate persists.
- [ ] **2. Verify red.** Run `./android/gradlew.bat -p android :app:testDebugUnitTest --tests '*AppViewModelTest*'`; failures must expose missing offline state/behavior.
- [ ] **3. Implement startup/read restoration.** Read current credential and matching cache on IO before attempting online boot. Restore only historical protected data, with onboarding closed; keep saved drafts but do not persist them. Refresh compatibility/me/setup/dashboard, editor metadata, and Activity on normal refresh; independent section failures preserve old section/time without authorizing its writes. Always fetch/cache editor on normal refresh when dashboard has an active package, not only on navigation. A successful absent/replaced package clears old editor. Existing tests need coherent package fixtures, not weaker identity checks.
- [ ] **4. Implement write/update boundaries.** Apply computed gates to `mutation`, `mediaMutation`, direct OAuth/asset submissions, `setDraft`, `editRanges`, `discardMediaTrims`, consent acknowledgement, and other local edit entry points. Reset authority/config/editor freshness on network epoch change; trigger reconnect reads even if previous work was busy. Preserve uncertain-command handling; do not replay writes. Version-gate persistence also works without a paired client; fresh compat clears installed-code-specific rejection only after success. Persist under session-generation/binding checks; capture epoch for freshness, but do not throw away acknowledged writes merely because connectivity changed.
  Serialize disk commit/invalidation under `SessionStore` then `SnapshotStore` lock order, on IO; never acquire these in reverse. Check generation/current credential inside that boundary before update/clear, so cache commits cannot race session replacement. Handle cache-write failure separately from API action failure. MainActivity temporarily constructs shared SnapshotStore directly until Task 5 exposes runtime property; do not leave production on nullable test default.
- [ ] **5. Verify green.** Run Task 4 command and full `:app:testDebugUnitTest`; startup/editor/onboarding/session regressions remain green.
- [ ] **6. Commit Task 4 paths.** `git commit -m "feat(android): restore read-only offline state"`.

### Task 5: Suspend transfers without losing intent or progress

**Files:** Modify `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadRuntime.kt`, `UploadEngine.kt`, `MainActivity.kt`, `android/app/src/test/java/com/dojo/aisomedo/uploads/UploadEngineTest.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/uploads/UploadRuntimeAndroidTest.kt`, and `BackgroundUploadTest.kt`. Modify `UploadJobs.kt`/`UploadScheduler.kt` only if new tests expose rescheduling loss; retain platform adapters/constraints.

**Interfaces:** Runtime produces `val snapshots: SnapshotStore` in `context.noBackupFilesDir.resolve("offline")` and `fun setWriteAccess(origin: String, bindingId: String?, allowed: Boolean): Unit`. Existing select/retry/dismiss/resolve signatures stay unchanged but check access against current binding. Append `connected: () -> Boolean = { true }` and `onUpdateRequired: (UploadRecord, String?) -> Unit = { _, _ -> }` to UploadEngine constructor; add `fun suspendTransfers(): Unit` cancelling active attempt jobs without row mutation. The callback carries HTTP 426's update URL to runtime before errors are collapsed to UploadIssue/QueueOutcome, with origin/binding from the row. Offline `resume(id, replacement = null)` accepts only already-paused transferable rows and retains identity; replacement and expired/fresh retries require online write access.

- [ ] **1. Write failing engine/runtime cases.** In engine fixture inject connected flag; use existing `putStarted`, delayed/lost response, counters, and store. `disconnectPreservesActiveIntentAndRetryBudget`: after first acknowledgement, disconnect/cancel; `intent == ACTIVE`, failures unchanged, known ID/identity/ranges retained. `reconnectSendsOnlyMissingChunks`: restore connection and run; `initializations == 0`, same upload ID, PUT offsets exclude acknowledged chunk. `offlinePauseResumeSendsNoRequests`: pause/resume existing row offline retains identity/progress and changes only local intent/phase. Runtime `offlineMutationAndLatePickerCallbacksAreRejected` checks select/reselection/retry/dismiss/resolve preserve rows and send zero requests. `background426PersistsBeforeSessionStops` reads store after 426, asserting `rejectedVersionCode == BuildConfig.VERSION_CODE`, safe supplied URL persisted or known URL retained when absent/unsafe, and no Activity required. Include 426 from authentication, chunk upload, and conflict refresh. Existing user-pause/restart, old-binding, server-retry, and force-stop cases must remain valid.
- [ ] **2. Verify red.** Run `./android/gradlew.bat -p android :app:testDebugUnitTest --tests '*UploadEngineTest*'` and compile instrumentation; execute new runtime cases on dedicated emulator if available.
- [ ] **3. Implement application-owned suspension and access.** Observe monitor on runtime IO scope; disconnected clears interactive access and calls `suspendTransfers`, never `stopSession`. Engine checks connected before new attempts and between operations; offline exceptions/cancellation do not consume failures or erase received state. Reconnect wakes eligible constrained work without resetting online server retry policy; notify scheduler even when no Activity is attached. Serialize pause/resume with current action/revision fences; avoid reactivating expired/failed/conflict rows through offline resume. Block network preview/refresh while offline. Gate known unsupported-version startup before work; persist background 426 under current binding before stopping/surfacing update issue. Wire the callback for all engine 426 catch paths; runtime also records raw conflict/preview ApiFailure paths. Invalid/absent URLs retain prior safe value; cache failure must not suppress the in-memory update gate or allow another transfer.
  MainActivity passes `uploads.snapshots` to model and observes model state to call `setWriteAccess` with current origin/binding/predicate. Runtime predicates also check actual connectivity and binding at execution, not stale picker-launch state. Fresh conflict status/authentication remains necessary even after shared access becomes true. No extra worker/foreground service.
- [ ] **4. Verify green.** Run engine tests, full host unit suite, instrumentation assembly, then new runtime/background cases on API 33 and API 34+ test emulators if available. Assert server IDs/ranges/offsets, not visual progress animation.
- [ ] **5. Commit Task 5 paths.** `git commit -m "fix(android): preserve uploads across disconnects"`.

### Task 6: Present historical data and disable all mutation controls

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/ui/ActivityScreen.kt`; modify `ui/DojoApp.kt`, `ui/MediaEditorPanel.kt`, `ui/UploadPanel.kt`, `ui/ConflictControls.kt`, `onboarding/OnboardingScreen.kt`, `onboarding/BrandingSteps.kt`, `onboarding/InstagramStep.kt`, and `android/app/src/main/res/values/strings.xml`. Test in existing `ui/DojoAppTest.kt`, `MediaEditorPanelTest.kt`, `UploadPanelTest.kt`, `onboarding/OnboardingTest.kt` under `android/app/src/androidTest/java/com/dojo/aisomedo/`.

**Interfaces:** `@Composable fun ActivityScreen(page: ActivityPageOut?, fetchedAt: Long?, busy: Boolean, onRefresh: () -> Unit)` and `fun activityActorLabel(actor: JsonElement): String?` in same file; string actor returned literally, client actor uses decoded `ClientRefOut.name`, malformed actor returns null for externalized unavailable fallback. Append `canMutate: Boolean = true` to UploadPanel/ConflictControls and MediaEditorPanel (latter receives `state.canEditMedia`). Preserve positional call compatibility; production always supplies explicit value.

- [ ] **1. Write failing UI cases.** `offlineCacheRemainsNavigableWithTimestamp` asserts four navigation destinations and package/Activity history remain visible. `offlineControlsDisabledExceptTransferPauseResume` asserts upload select/retry/reselection/dismiss/conflict, drag/range/save/discard, config/consent/OAuth controls disabled; pause/resume enabled for eligible existing rows. `historyMissingAndEmptyHaveDifferentCopy` asserts distinct externalized states. `missingUpdateUrlExplainsUnavailableDownload` asserts update gate with explanation/no download button. `pickerResultAfterDisconnectDoesNotInvokeMutation` flips latest access before permission/document result and asserts select/resume callback counters stay zero. Actor tests cover literal/object/invalid JSON and plain server action text (no HTML interpretation).
- [ ] **2. Verify red.** Run targeted device classes when emulator available; otherwise compile and record test execution blocked, rather than calling compilation red/green evidence.
- [ ] **3. Implement existing-component presentation.** Replace Activity placeholder with latest-page component. Show offline/backend-unavailable notice and independent last-fetch labels using existing timestamp formatting conventions. Missing package/editor cache must not reuse "no active package" copy; timestamps distinguish successful no-package reads. Never initiate unavailable previews offline. Apply explicit predicates to all controls and picker/permission callbacks via current state (`rememberUpdatedState` where needed), retaining model/runtime enforcement. Freeze local text/date/range/checkbox/drag edits; historical navigation/inspection stays enabled. Cancel an active drag when gate changes. Append enabled input only where existing busy flag cannot express read-only state. Add Turkish resources; preserve semantic headings/live regions/touch targets.
- [ ] **4. Verify green/compile.** Run full host tests, debug assembly, instrumentation assembly, and available targeted UI classes. Inspect phone/tablet, large text, and TalkBack behavior on dedicated devices; record unrun cases.
- [ ] **5. Commit Task 6 paths.** `git commit -m "feat(android): show cached history and read-only UI"`.

### Task 7: Record acceptance evidence and review whole diff

**Files:** Create `docs/verification/issue-37-android-offline.md` and `docs/rehberler/issue-37-android-cevrimdisi-deneme-rehberi.md`; update checklist/status in approved spec and this plan only for stages actually completed. Correct product defects in owning task files, with regression checks.

**Interfaces:** Consumes Tasks 1–6. Produces reproducible host/device evidence, Turkish manual walkthrough, and explicit acceptance gaps.

- [ ] **1. Run host verification from repository root.** All must exit 0:

```powershell
uv run --project backend pytest backend/tests/test_client_generation.py -q
uv run --project backend ruff check backend/scripts/generate_clients.py backend/tests/test_client_generation.py
uv run --project backend python backend/scripts/generate_clients.py
git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
git diff --check
```

- [ ] **2. Execute device acceptance safely.** On dedicated API 33 and API 34+ emulators, run `./android/gradlew.bat -p android :app:connectedDebugAndroidTest` with explicit `ANDROID_SERIAL`. Record serial/API/test counts. Prove offline warm/cold reads, pause/resume, missing-only chunks, Home/screen-off reconnect, and persistent update gate. Use synthetic backend/media; process-death/force-stop check needs a host-owned backend, since an in-app MockWebServer dies with the app. Restore network/device state after every test. No connected test device means blocked, not passed.
- [ ] **3. Review complete change against spec.** Verify every mutation entry point/UI callback, session/store lock order, partial reads, both schedulers, and Review Focus cases. Add regressions for findings, rerun affected suites and final host checks. Use selected execution method's whole-branch reviewer; do not claim review of #36 actions that do not exist.
- [ ] **4. Write evidence and Turkish walkthrough.** Include commands/counts, outage/restart/update steps, cache limitations, signing/distribution boundary, and every outstanding device/manual check. Keep issue open if acceptance remains unverified; closing/pushing/PR creation requires user's integration choice.
- [ ] **5. Commit Task 7 paths.** `git commit -m "docs(android): record issue 37 offline checks"`.

## Plan self-review and handoff

- [x] Spec sections map to Tasks 1–7; independent Activity reads, origin-scoped pre-pair update gate, cached editor fetch on normal refresh, and absent-section copy are included.
- [x] Interfaces agree across storage, network, model, runtime, and UI; no unspecified external helper/package is required.
- [x] Five Review Focus conditions have named owning tests.
- [x] Test steps name assertions, commands identify red/green evidence, and commits stage only task-owned paths.
- [ ] User reviews plan and chooses Native or Subagent-driven execution.

Recommended: **Native**. Tasks share model/runtime/DTO interfaces; implementing
sequentially in one session minimizes repeated context, with one fresh whole-branch
reviewer after host/device checks.
