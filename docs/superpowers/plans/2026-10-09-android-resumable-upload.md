# Android Resumable Background Uploads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #33 with background photo/video uploads into the Aktif Paket, progress, pause/retry, reconnect recovery, and pre-transfer limits.

**Architecture:** One durable sequential queue and shared checksummed transfer engine. Android 14+ uses native user-initiated data transfer jobs; Android 10–13 uses foreground WorkManager workers. Compose observes state without owning transfer execution; the existing backend and encrypted SessionStore remain authoritative.

**Tech Stack:** Kotlin, Jetpack Compose, coroutines, Kotlin serialization, OkHttp, Android JobScheduler/Storage Access Framework, WorkManager, existing JUnit/MockWebServer/Compose tests.

**Spec:** `docs/superpowers/specs/2026-10-09-android-resumable-upload-design.md` (approved).

## Global Constraints

- Android 10–13: API 29–33 foreground CoroutineWorker; Android 14+: API 34+ UIDT JobService.
- Fixed 2 MiB chunks, SHA-256, Long byte sizes/offsets/progress, bounded memory, no whole-media copies.
- Five consecutive transient failures per file, reset on acknowledged progress; manual retry after exhaustion.
- Durable pause intent precedes cancellation; OS interruption preserves active intent; force-stop is respected.
- Metadata lives in private no-backup storage; bearer tokens remain only in encrypted SessionStore.
- Reuse existing upload APIs and generated DTOs; no backend/schema redesign or conflict-resolution UI.
- Externalized Turkish copy, labelled progress/actions, existing adaptive shell; no broad media/storage permission.
- WorkManager is the only new product dependency; use existing test tools and optional matching WorkManager test helpers.

## Review Focus

1. Provider reports unknown/inaccurate size or short reads: determine actual length safely and send zero chunks on rejection (Task 2).
2. Cancellation races with accepted PUT/complete and another queued file: preserve pause, reconcile accepted bytes, continue siblings (Task 3).
3. Re-pair at the same origin while an old callback is pending: never attach old records or clear a new credential (Tasks 2 and 5).
4. Android refuses scheduling or notification permission: retain recoverable state, explain restriction, avoid crashes (Task 4).
5. Two rows share a URI and one is dismissed: retain the other's durable access and never delete original media (Task 5).

## File Map and Shared Interfaces

All paths are relative to the repository root. Implement in task order.

| File | Responsibility |
| --- | --- |
| `backend/scripts/generate_clients.py` | Generate consumed upload DTOs, Long byte fields, arbitrary JSON conflict metadata, Kotlin collection defaults |
| `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt` | Regenerated models only |
| `android/app/src/main/java/com/dojo/aisomedo/api/DojoApi.kt` | Existing authenticated transport plus limits/init/status/range/complete |
| `android/app/src/main/java/com/dojo/aisomedo/auth/SessionStore.kt` | Atomic credential/binding snapshot; preserve existing API |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadState.kt` | Serializable records, identity, intent/phase/error enums, engine outcome |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadStore.kt` | Atomic validated metadata, revision-guarded mutations, StateFlow |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadSource.kt` | SAF metadata/grants/stream opening, bounded preparation and identity verification |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadEngine.kt` | Shared queue execution and resumable protocol |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadRuntime.kt` | Application-context singleton, actions, session fencing, scheduler coordination |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadScheduler.kt` | Stable unique scheduling identity and API-level routing |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadJobs.kt` | UploadJobService and UploadWorker adapters |
| `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadNotifications.kt` | Notification channel, progress, pause receiver, tap Intent |
| `android/app/src/main/java/com/dojo/aisomedo/ui/UploadPanel.kt` | Picker, upload rows, valid actions and accessibility |
| Existing `MainActivity.kt`, `AppViewModel.kt`, `ui/DojoApp.kt`, manifest, strings, app Gradle | Wiring only; keep unrelated behavior intact |

Use these concrete types (no general-purpose transport/storage abstraction):

- `FileIdentity(size: Long, chunkHashes: List<String>, fingerprint: String)`; `CHUNK_BYTES = 2 * 1024 * 1024`.
- `UploadIntent { ACTIVE, PAUSED }`; `UploadPhase { PREPARING, WAITING, UPLOADING, PAUSED, RETRYABLE, NEEDS_FILE, QUEUED, PROCESSING, FINALIZED, FAILED, CONFLICT, EXPIRED }`.
- `UploadIssue { NETWORK, OVERSIZE, CAPACITY, PACKAGE_CHANGED, CHECKSUM, WRONG_FILE, FILE_ACCESS, STORAGE, SCHEDULING, NOTIFICATIONS, EXPIRED, CONFLICT, AUTH, UPDATE_REQUIRED, SERVER, INVALID_RESPONSE }`.
- `UploadRecord` is serializable: `id/origin/bindingId/uri/filename/contentType: String`, `clientId: Int`, `size: Long?`, `identity: FileIdentity?`, `status: UploadOut?`, `intent: UploadIntent`, `phase: UploadPhase`, `issue: UploadIssue?`, `diagnostic: String?`, `revision: Long`, `failures: Int`, `retryAtMillis: Long?`. New records use revision/failures 0, ACTIVE/WAITING, and null optional state. File preparation progress is transient UI state, not persisted on every read.
- `SessionCredential(bindingId: String, token: String)` is an ordinary class with no secret-bearing toString; it is never serialized.
- `UploadFailure(val issue: UploadIssue)` is an Exception with an issue-code-only message, defined in UploadState.kt. Preparation/storage validation throws it; callers map its issue to localized copy.
- `QueueOutcome { IDLE, RETRY, AUTH_REQUIRED, UPDATE_REQUIRED }`; system cancellation throws CancellationException rather than manufacturing an outcome.

### Task 1: Large-file contract and authenticated upload transport

**Files:** Modify `backend/scripts/generate_clients.py`, `backend/tests/test_client_generation.py`, `android/app/src/main/java/com/dojo/aisomedo/api/DojoApi.kt`; regenerate `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`; extend `android/app/src/test/java/com/dojo/aisomedo/api/DojoApiTest.kt`.

**Interfaces:** Preserve `kotlin_models(schema: dict, roots: list[str]) -> str` and existing constructors. Produce DojoApi suspending methods `uploadLimits(): UploadLimitsOut`, `startUpload(body: UploadInitIn): UploadOut`, `uploadStatus(id: String): UploadOut`, `uploadRange(id: String, offset: Long, checksum: String, bytes: ByteArray): UploadOut`, `completeUpload(id: String): UploadOut`. Add optional `detail: String? = null` to ApiFailure after its existing arguments; its message/toString remains status-only.

- [ ] **1. Write failing generator and transport tests.** Extend `test_upload_generation_emits_wire_types` to check Kotlin output:

  ```python
  kotlin = module.ANDROID_TARGET.read_text(encoding="utf-8")
  assert "val maxFileBytes: Long" in kotlin
  assert "val declaredSizeBytes: Long" in kotlin
  assert "val receivedBytes: Long" in kotlin
  assert "val receivedRanges: List<List<Long>>" in kotlin
  assert "val conflicts: List<Map<String, JsonElement>> = emptyList()" in kotlin
  assert "val androidMinVersionCode: Int" in kotlin
  ```

  Add `uploadMethodsPreserveLargeOffsetsAndCancellation` and `uploadErrorsStaySecretFree` in DojoApiTest: decode 2147483648 bytes; assert range offset 2147483648 in URL, checksum/body/headers correct, cancelled PUT not retried, redirects refused, nested conflict JSON decodes, malformed status fails safely, and detail does not appear in exception messages.
- [ ] **2. Run red.** From root: `uv run --project backend pytest backend/tests/test_client_generation.py -v`; `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "com.dojo.aisomedo.api.DojoApiTest"`. Expect new assertions/missing methods to fail, not an unrelated environment error.
- [ ] **3. Implement generator changes.** Add UploadLimitsOut/UploadInitIn/UploadOut roots. Map only upload byte/limit/range properties to Long recursively, leaving IDs/version fields Int. Map unstructured object values to JsonElement and emit `emptyList()` for empty array defaults; add required generated import. Preserve existing nullable/default behavior and constructor compatibility.
- [ ] **4. Implement transport methods** over existing `bytes`/`request`, bounded error-detail parsing and same-origin URL encoding. Require nonnegative offset, valid SHA-256, and nonempty chunks no larger than `2 * 1024 * 1024` bytes (Task 1 must build before Task 2 defines CHUNK_BYTES). Do not change branding upload limits. Regenerate with `uv run --project backend python backend/scripts/generate_clients.py`.
- [ ] **5. Run green** using Step 2 commands; run generator twice and confirm byte-identical output and no web/OpenAPI drift. Existing API and generation tests must remain green.
- [ ] **6. Commit only Task 1 files:** `feat(android): add resumable upload API`.

### Task 2: Durable records, pairing binding, and bounded file preparation

**Files:** Create UploadState.kt, UploadStore.kt, UploadSource.kt from the file map. Modify `android/app/src/main/java/com/dojo/aisomedo/auth/SessionStore.kt` and existing SessionStoreTest.kt. Create `android/app/src/test/java/com/dojo/aisomedo/uploads/UploadStoreTest.kt`, `UploadSourceTest.kt` in the same directory; create `android/app/src/androidTest/java/com/dojo/aisomedo/uploads/UploadSourceAndroidTest.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/uploads/UploadTestDocumentsProvider.kt`, and `android/app/src/androidTest/AndroidManifest.xml` for synthetic persistable document access tests.

**Interfaces:** Consume Task 1 UploadOut. Produce `SessionStore.readSession(origin: String): SessionCredential?`, `clearTokenIfBinding(origin: String, bindingId: String): Boolean`; `UploadStore(directory: File)` with `val rows: StateFlow<List<UploadRecord>>`, `put(record): Unit`, `mutate(id: String, expectedRevision: Long? = null, change: (UploadRecord) -> UploadRecord): UploadRecord?`, `remove(id: String): Unit`. Produce `UploadSource(resolver: ContentResolver)` with `retain(uri: Uri): SelectedDocument`, `open(uri: String): InputStream`, `release(uri: String): Unit`; `SelectedDocument(uri: String, filename: String, contentType: String, size: Long?)`. Pure suspending helpers: `prepareFile(open: () -> InputStream, declaredSize: Long?, maxBytes: Long, onProgress: (Long) -> Unit): FileIdentity`, `verifyFile(open: () -> InputStream, expected: FileIdentity, onProgress: (Long) -> Unit): Unit`.

- [ ] **1. Write red tests.** `recordsReloadAndRejectStaleMutation`: assert same identity/ID after store recreation, mutation increments revision, stale expectedRevision returns null, paused intent survives reload. `corruptionAndFailedWritesCannotSchedule`: malformed/version-mismatched/oversized records excluded, failed write surfaces storage error. `pairingBindingRotatesWithoutLeakingCredentials`: existing token roundtrip preserved, same-origin resave changes binding, clearToken invalidates it, serialized records never contain token; clearTokenIfBinding(oldBinding) returns false after resave and leaves new token untouched.

  `preparationIsBoundedAndChecksActualLength`: assert `(2 MiB + 1)` gives two hashes; unknown size is measured; zero bytes, maxBytes+1, and inaccurate declared length fail. Custom short-read/non-seekable streams produce identical fingerprints; cancellation closes streams. `changedBytesFailVerification`: same name/size but different bytes is rejected. Android source test asserts retained read access survives a recreated source; missing grant/permission becomes FILE_ACCESS, with no broad storage permission.

  ```kotlin
  @Test fun preparationIsBoundedAndChecksActualLength() = runBlocking {
      val bytes = ByteArray(CHUNK_BYTES + 1)
      val identity = prepareFile({ bytes.inputStream() }, null, 2L * CHUNK_BYTES) {}
      assertEquals(CHUNK_BYTES.toLong() + 1, identity.size)
      assertEquals(2, identity.chunkHashes.size)
  }
  ```
- [ ] **2. Run red:** `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "com.dojo.aisomedo.uploads.Upload*Test" --tests "com.dojo.aisomedo.auth.SessionStoreTest"`. Compile source instrumentation tests once implementation exists; run them in Task 6.
- [ ] **3. Implement atomic binding/state.** Define SessionCredential in auth/SessionStore.kt. Derive opaque bindingId from SHA-256 of encrypted credential bytes in the same synchronized snapshot that decrypts token, not from plaintext token. clearTokenIfBinding checks and clears under that same lock; old failures cannot clear a newer pairing between check and delete. Share one SessionStore instance in production. Store schema version 1 and individual UUID-named JSON records with a 1 MiB serialized limit; fsync temporary file then atomic replace. One same-process lock guards mutations; always increment revision on accepted changes. Validate origin, positive size when known, hashes/count/identity/status, enum values and nonnegative counters. A bad record cannot stop loading other valid records; a write failure cannot publish success.
- [ ] **4. Implement SAF/stream preparation.** Retain persistable grants, query OpenableColumns metadata/MIME, use fallback display filename, normalize invalid/unknown size as unknown. Fingerprint SHA-256 of UTF-8 `"${size}:${CHUNK_BYTES}:"` followed by concatenated ordered lowercase chunk hashes; stream with a reused chunk buffer, cancellation checks and actual-size/limit checks. Verify each hash; do not allocate full media or rely on InputStream.skip always advancing. Mark metadata-size and single-process-lock ceilings with focused `ponytail:` comments.
- [ ] **5. Run green** with Step 2 command plus `:app:assembleDebugAndroidTest`; assert existing credential tests remain green and preparation buffers never exceed CHUNK_BYTES.
- [ ] **6. Commit Task 2 files:** `feat(android): persist upload state and identity`.

### Task 3: Shared resumable queue engine

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/uploads/UploadEngine.kt` and `android/app/src/test/java/com/dojo/aisomedo/uploads/UploadEngineTest.kt`; modify UploadState.kt only for required engine-local state.

**Interfaces:** Consume Tasks 1–2. Produce `UploadEngine(store: UploadStore, open: (String) -> InputStream, session: (UploadRecord) -> SessionCredential?, api: (UploadRecord, SessionCredential) -> DojoApi, now: () -> Long)`; suspending `run(onProgress: (UploadRecord) -> Unit): QueueOutcome` and `refresh(): Unit`; `cancel(id: String): Unit`. Factory callbacks exist for current credentials/real HTTP and runnable JVM tests, not a new generic transport interface.

- [ ] **1. Write red MockWebServer tests** with deterministic coroutine time and temporary records. `resumesKnownIdAfterLostPutResponse`: server acknowledges first chunk but drops response; rerun GETs same ID, does not POST init, sends only missing chunk. `lostCompleteResponseReconcilesQueued`: accepted completion followed by disconnect must not resend chunks/create upload. `limitsAndCapacityRejectBeforeTransfer`: empty/oversize and init 413/409 produce zero PUTs.

  `pauseRaceDoesNotReviveRowOrBlockSibling`: pause revision changes before delayed PUT returns; row remains paused, next file runs. `fiveFailuresRequireManualRetry`: fifth consecutive transient failure leaves RETRYABLE and no automatic sixth attempt, acknowledged progress resets count. `terminalAndInvalidStatusesStopChunks`: wrong ID/size/bounds, conflict, failed, aborted and 404 send no further PUT. `sourceChangesAndStorageFailuresStopBeforePut`: identity or durability failure never transmits unverified bytes. `systemStopKeepsActiveIntent`: cancelled engine leaves durable ACTIVE state and closes its input/call. `duplicateRunsDoNotDuplicateChunks`: queue guard permits one runner.

  In `resumesKnownIdAfterLostPutResponse`, arrange size CHUNK_BYTES+1, known ID `saved`, server-confirmed range `[0, CHUNK_BYTES)`, and collect PUT offsets/initialization count from MockWebServer:

  ```kotlin
  assertEquals(listOf(CHUNK_BYTES.toLong()), putOffsets)
  assertEquals(0, initializationCount)
  assertEquals("saved", store.rows.value.single().status!!.uploadId)
  ```
- [ ] **2. Run red:** `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "com.dojo.aisomedo.uploads.UploadEngineTest"`.
- [ ] **3. Implement preparation/init/reconciliation.** Validate positive server limits before preparation, include expectedPackageId in init, persist ID before any PUT. At each new engine run, validate api.me() is the record's non-revoked device client. Recheck session/binding and record revision before requests and writes. Validate ranges as backend half-open intervals, bounded by size with received byte count matching merged coverage. Skip full covered chunks; partially covered chunks retransmit idempotently. Re-open/scan source sequentially once per transfer pass; reverify identity on resumed engine runs.
- [ ] **4. Implement status/error/queue behavior.** Complete only after confirmed full coverage; reconcile ambiguous responses without fresh init. Treat unknown-ID init loss as manual-retry-only. Process rows sequentially; failed/paused/server-processing rows do not monopolize queue. Track transient retry deadlines with exponential 30-second base, capped at five hours, and five consecutive failures; return RETRY when only delayed eligible work remains. Reset failures/deadline on confirmed progress. Propagate OS cancellation; user pause cancels row child job only. Refresh GETs known queued/processing rows without sending chunks and emits finalized state for shell refresh.
- [ ] **5. Run green** using Step 2 and all Task 1–2 tests. Inspect request logs for exact upload IDs, offsets and no hidden automatic OkHttp retries.
- [ ] **6. Commit Task 3 files:** `feat(android): resume checksummed media transfers`.

### Task 4: Background scheduling, runtime, and notifications

**Files:** Create UploadRuntime.kt, UploadScheduler.kt, UploadJobs.kt, UploadNotifications.kt from file map. Modify `android/app/build.gradle.kts`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/res/values/strings.xml`; create `android/app/src/main/res/drawable/ic_upload.xml`. Create `android/app/src/test/java/com/dojo/aisomedo/uploads/UploadSchedulerTest.kt` and `android/app/src/androidTest/java/com/dojo/aisomedo/uploads/UploadJobsAndroidTest.kt`.

**Interfaces:** Consume Task 3 engine/QueueOutcome. Produce `enum SchedulerKind { UIDT, WORK_MANAGER }`, `schedulerKind(apiLevel: Int): SchedulerKind`; `UploadScheduler(context: Context)` with `schedule(bindingId: String): Boolean`, `cancel(bindingId: String): Unit`. `UploadRuntime.get(context: Context): UploadRuntime` owns one application-scope session store, upload store, scheduler/engine and active jobs; exposes `val rows: StateFlow<List<UploadRecord>>`, `val sessionStore: SessionStore`, `val issue: StateFlow<UploadIssue?>`, `attach(origin: String, clientId: Int): Unit`, suspending `select(uris: List<Uri>): Unit`, `pause(id: String): Unit`, `resume(id: String, replacement: Uri? = null): Unit`, `retry(id: String, replacement: Uri? = null): Unit`, `dismiss(id: String): Unit`, `refresh(): Unit`, `stopSession(): Unit`, and `runQueue(onProgress: (UploadRecord) -> Unit): QueueOutcome`. Runtime refresh/runQueue are suspending; other actions launch their application-scope work without blocking the main thread. Publish selection/storage/scheduling failures through issue even when no row could be saved.

- [ ] **1. Write red routing/action tests:** `assertEquals(WORK_MANAGER, schedulerKind(29))`, repeat for 33; `assertEquals(UIDT, schedulerKind(34))`, repeat for 36. Android tests assert unique queue scheduling, real engine invoked from both adapters, network constraint, required notification before long-running transfer, and that notification pause mutates durable intent. Include denied notification permission, rejected JobScheduler result and rejected foreground start: no crash or lost row; show actionable issue. Duplicate PendingIntent actions cannot restart paused work.
- [ ] **2. Run red:** `./android/gradlew.bat -p android :app:testDebugUnitTest --tests "com.dojo.aisomedo.uploads.UploadSchedulerTest"`; instrumentation red/green on API 33 and 34+ in Task 6. Before implementation read current official APIs from spec references.
- [ ] **3. Add required platform wiring.** Pin `androidx.work:work-runtime:2.10.5` (compiled against SDK 35; CoroutineWorker is in work-runtime), optional `androidTestImplementation("androidx.work:work-testing:2.10.5")`. Keep compileSdk/targetSdk 35/minSdk 29 and current toolchain. Declare ACCESS_NETWORK_STATE, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS, RUN_USER_INITIATED_JOBS; non-exported JobService with BIND_JOB_SERVICE, non-exported pause receiver, WorkManager SystemForegroundService merge with dataSync type. No multiprocess service or upload-specific Application is needed.
- [ ] **4. Implement runtime and platform adapters.** UIDT: job ID 3300 with current binding in extras, schedule from visible select/resume/retry, `setUserInitiated(true)`, network requirement/estimated bytes, required notification, async coroutine callbacks; call jobFinished with engine RETRY result and preserve intent on OS stop. WorkManager: unique name `dojo-upload-<bindingId>`, KEEP work, connected-network constraint, exponential backoff, `setForeground` with dataSync, engine RETRY → Result.retry(). Honor row retry deadlines and abandon exhausted rows without discarding other eligible work. Catch scheduling/foreground failures, cancel stopped calls, serialize engines with shared guard, and rerun/reconcile active records on app reopen as platform permits. A stale binding must not cancel the newer binding's fixed job ID.
- [ ] **5. Implement notification/actions.** Channel ID `dojo-uploads`, notification ID 3301, externalized title/status/progress, throttled updates after confirmed chunks, immutable explicit pause/tap intents scoped to current binding/row. Pause action invokes runtime pause; cancel platform queue only if no eligible rows remain. Tap carries package destination to MainActivity. Request notification permission in UI task; denial is observable without falsely promising a visible notification. Stop service/job once all client-side transfers are queued/terminal rather than polling server processing forever.
- [ ] **6. Run green:** routing tests, `./android/gradlew.bat -p android :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest`. Verify merged manifest and run adapter tests on available devices, recording missing API coverage for Task 6.
- [ ] **7. Commit Task 4 files:** `feat(android): run uploads in background`.

### Task 5: Aktif Paket UI and session lifecycle integration

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/ui/UploadPanel.kt`. Modify `android/app/src/main/java/com/dojo/aisomedo/MainActivity.kt`, `AppViewModel.kt`, `ui/DojoApp.kt`, `android/app/src/main/res/values/strings.xml`. Extend `android/app/src/test/java/com/dojo/aisomedo/AppViewModelTest.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/ui/DojoAppTest.kt`; create `android/app/src/androidTest/java/com/dojo/aisomedo/ui/UploadPanelTest.kt` and `android/app/src/androidTest/java/com/dojo/aisomedo/uploads/UploadRuntimeAndroidTest.kt`.

**Interfaces:** Consume Task 4 runtime/actions. Produce composable `UploadPanel(rows: List<UploadRecord>, issue: UploadIssue?, onSelect: (List<Uri>) -> Unit, onPause: (String) -> Unit, onResume: (String, Uri?) -> Unit, onRetry: (String, Uri?) -> Unit, onDismiss: (String) -> Unit)` with SAF/notification launchers. Change DojoApp to `DojoApp(model: AppViewModel, uploads: UploadRuntime? = null, openUrl: (String) -> Unit)` so existing `DojoApp(model) { ... }` calls remain valid; update positional calls found by blast-radius search. Add optional `onSessionStopped: () -> Unit = {}` at end of AppViewModel constructor; call it on server change/authenticated 401/426 before clearing shell state. Add `observeSessionFailure(issue: UploadIssue): Unit` to route background auth/update errors through existing failure logic without leaking credentials.

- [ ] **1. Write red UI/session tests.** Rows show correct Turkish actions/progress semantics: PAUSED exposes resume, RETRYABLE retry, NEEDS_FILE original-file picker, CONFLICT explains blocked state without overwrite. Preparation is not upload percentage; 100% transferred plus PROCESSING is not finalized success. Long filenames wrap at phone/tablet widths; phase announcements do not announce every byte.

  `backgroundAuthFailureReturnsToPairing`: runtime 401 clears matching credential, model enters PAIRING; 426 gates mutation. `lateOldPairingCannotClearNewCredential`: re-pair same origin while old request delayed; old failure writes/cleanup ignored, new credential untouched. `sharedUriDismissalRetainsOtherRows`: dismissal releases grant only when no remaining row needs it; original file persists. Rotation/navigation keep one engine and uploaded ID; notification tap selects PACKAGE. Keep original four-area/no-package-creation tests valid.

  A single PAUSED row's UI assertions (copy is fixed below):

  ```kotlin
  compose.onNodeWithText("Devam et").assertExists()
  compose.onNodeWithText("Duraklat").assertDoesNotExist()
  compose.onNodeWithTag("upload-progress-${record.id}").assert(
      SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo)
  )
  ```
- [ ] **2. Run red:** existing AppViewModel tests and targeted instrumentation using `./android/gradlew.bat -p android :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.UploadPanelTest` on an available emulator.
- [ ] **3. Wire lifetime and safety.** MainActivity obtains runtime singleton and passes its SessionStore to model; production always passes runtime to DojoApp. Attach only after READY paired state, observe issue with lifecycle collection and route only AUTH/UPDATE_REQUIRED to observeSessionFailure; other issues appear in panel. Refresh known statuses on model/app foreground refresh without concurrent duplicate GETs. Bind upload rows separately from busy onboarding state. User actions persist intent/revision before scheduling. stopSession fences metadata/calls before session mutation; matching-binding checks prevent old background failures clearing newer credentials. Existing branding remains unchanged.
- [ ] **4. Implement panel/picker.** Use ACTION_OPEN_DOCUMENT multiple selection with supported MIME guidance/persistable grants, original-file reselection per row, notification permission launcher on API 33+. Add externalized labels `upload_select` = `Fotoğraf/video seç`, `upload_pause` = `Duraklat`, `upload_resume` = `Devam et`; reuse existing retry label. Tag progress `upload-progress-<record.id>`. Keep PackageSummary, replace package_read_only copy with upload panel, reuse existing material components/Turkish resources. Build row state directly from backend-confirmed records, show safe escaped diagnostics, refresh dashboard after finalized status. Route new-upload retry for failed/expired to fresh limits/identity only on explicit action; never overwrite conflicts.
- [ ] **5. Run green:** all Android unit tests, targeted UI/runtime instrumentation and existing DojoApp tests; rotate/navigate during transfer and verify one queue. Document unavailable emulator checks rather than marking them passed.
- [ ] **6. Commit Task 5 files:** `feat(android): add package upload controls`.

### Task 6: End-to-end background proof and final checks

**Files:** Create `android/app/src/androidTest/java/com/dojo/aisomedo/uploads/BackgroundUploadTest.kt`, `docs/verification/issue-33-android-upload.md`, `docs/rehberler/issue-33-android-upload-deneme-rehberi.md`. Extend Task 2's UploadTestDocumentsProvider.kt and test manifest for background scenarios; modify README.md with a short Android upload usage/evidence link. Fix only failures caused by this implementation.

**Interfaces:** Consume real runtime/source/schedulers/UI and existing MockWebServer; no new application interfaces. Keep synthetic documents/server in test scope; no real credentials or production media.

- [ ] **1. Write failing background integration checks** using an instrumentation-only persistable test DocumentsProvider and throttled synthetic multi-chunk upload. `backgroundAndScreenOffContinueTransfer`: begin from visible Activity, use platform UiAutomation.executeShellCommand to send Home/screen-off events, observe confirmed server offsets advancing under UIDT/WorkManager; no UIAutomator dependency needed. `disconnectAndSystemStopResumeKnownId`: stop connection/job after acknowledged chunk, recreate runtime/process as applicable, reconnect/reopen; same server ID, acknowledged chunks skipped. `notificationPauseStaysPausedAfterReopen`: pause from notification during delayed response, no later chunks until explicit resume. Assert oversize never initializes/chunks and finalized status refreshes package summary.

  Use server-confirmed byte counters and recorded initialization/ID logs, not UI-animation progress:

  ```kotlin
  assertTrue(confirmedAfterBackground > confirmedBeforeBackground)
  assertTrue(confirmedAfterScreenOff > confirmedBeforeScreenOff)
  assertEquals(originalUploadId, resumedUploadId)
  assertEquals(1, initializationCount)
  assertEquals(chunksAfterPause, chunksAfterReopenBeforeResume)
  ```
- [ ] **2. Run red** on API 33 and API 34+; API 29 and API 36 are additional manual compatibility checks. Use separate test emulator builds/state; never force-stop or clear the user's installed production app as a test. UI tests that cannot control process death run it as a documented host-driven scenario rather than pretending same-process recreation proves it.
- [ ] **3. Run green/device scenarios** and inspect server logs/job/service notifications. Explicit OS force-stop preserves bytes but must not be bypassed; reopening permits user resume. Check notification-denied, unknown-size provider, revoked access, duplicate pause/resume, and package-capacity rejection. Record Android/API/device IDs, commands, observed offsets/IDs, test counts, and any untested scenarios in verification doc. User guide uses Turkish instructions for background progress, pause/retry, reconnect, and platform restrictions.
- [ ] **4. Run complete automated gates** from repository root:

  ```powershell
  uv run --project backend pytest backend/tests/test_client_generation.py backend/tests/test_contract.py -v
  uv run --project backend ruff check backend/scripts/generate_clients.py backend/tests/test_client_generation.py
  uv run --project backend python backend/scripts/export_openapi.py
  uv run --project backend python backend/scripts/generate_clients.py
  ./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
  ./android/gradlew.bat -p android :app:connectedDebugAndroidTest
  git diff --check
  ```

  Generator must reproduce committed artifacts; backend/openapi.json and web DTOs stay unchanged. Run connected tests per representative API with their results attributed separately. When an SDK/emulator is unavailable, report blocked verification, not feature completion.
- [ ] **5. Obtain one fresh whole-branch review** against approved spec and changed files; use Native's reviewer or Subagent-driven's review workflow selected at handoff. Re-run affected checks after corrections. No merge/push/issue closure without user authorization.
- [ ] **6. Commit evidence and usage docs:** `test(android): verify background upload recovery`.

## Plan Self-Review

- Spec coverage: Task 1 contract/Long; Task 2 durable identity/access; Task 3 limits/ranges/retry/processing; Task 4 background/platform notifications; Task 5 session/UI/accessibility; Task 6 real-device evidence and usage.
- Interface consistency: both adapters run UploadRuntime.runQueue → UploadEngine.run; only runtime owns session/scheduling/actions; generated UploadOut is shared through all layers.
- Race/edge review: each Review Focus condition has its owner test above, including unknown length, pause/late callback, same-origin re-pair, scheduler rejection, and shared URI grants.
- No speculative database, duplicate HTTP client, background processing poller, whole-file cache, or unrelated refactor.
- Dependency decision: WorkManager 2.10.5 preserves existing SDK 35 build; release documentation at https://developer.android.com/jetpack/androidx/releases/work confirms 2.10 SDK 35 compilation and CoroutineWorker's presence in work-runtime.

## Execution Handoff

Plan approval and execution selection are still required. Recommend **Native**:
six tasks share the same queue/session interfaces, so inline implementation is
cheaper and avoids repeated context setup. One independent whole-branch reviewer
checks the finished changes. Subagent-driven adds an implementer and reviewer
gate per task if stronger intermediate isolation is preferred.
