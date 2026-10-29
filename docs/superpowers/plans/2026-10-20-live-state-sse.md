# Live State Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace foreground web/Android live-data polling with SSE, transactional concurrent editing, and durable device-local drafts.

**Architecture:** PostgreSQL owns editable package state and commits durable invalidations together with changes. One notification listener per API process fans out SSE signals; one foreground coordinator per client instance refreshes affected views and locks editing when synchronization is unhealthy. Existing HTTP reads and domain validation remain in use.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, PostgreSQL 18, existing Psycopg 3, FastAPI/Starlette; React 19.3.1, TypeScript, browser Fetch/IndexedDB; Kotlin, coroutines, existing OkHttp 4.12 and app-private files. Existing pytest, Vitest, Playwright, JUnit, and MockWebServer test infrastructure.

**Spec:** `docs/superpowers/specs/2026-10-20-live-state-sse-design.md`

## Global Constraints

- Initial scale: 2–10 simultaneously active clients.
- No periodic live-state data queries, including a low-frequency polling fallback.
- Changes originating in either the API or worker reach connected, authorized clients.
- PostgreSQL is the source of truth for editable package state.
- Independent media edits merge; conflicting edits require an explicit decision.
- A submitted group of edits either commits completely or does not commit.
- Loss of live connectivity disables editing and state-changing actions, not only saving.
- Local drafts survive application/browser closure on the same device and profile.
- Reconnection restores current state before editing becomes available.
- Transport defaults: 15-second heartbeat, 45-second no-traffic deadline; reconnect around one second initially, capped at 30 seconds, with jitter.
- No data backfill, cutover, backward-compatibility work, data resets, new background push behavior, or new message service. An additive schema revision is necessary product code, not a data-transition plan.
- Preserve worker scheduling, publication reconciliation, transfer protocols, existing media binaries, and existing artifact safety rules. Do not wrap network calls or rendering in a long database transaction.
- Use domain terms from `CONTEXT.md`; retain Turkish user-facing copy in existing localization patterns. Documentation remains English.
- Reuse installed dependencies and existing transaction/test seams. Generated clients must be regenerated, not hand-edited.

## Review Focus

- Fragmented UTF-8/SSE input, CRLF, oversized frames, and EOF must not fabricate a healthy connection or lose complete invalidations: Tasks 6 and 8 parser tests.
- A resource changes between stream readiness and first snapshot, or repeatedly during a read: Tasks 5, 6, and 8 must retain a deferred invalidation and reject stale responses.
- A response is lost after a commit, or the process dies during local replacement: Tasks 7 and 9 must preserve uncertainty/previous draft and reconcile without replaying mutations.
- Two tabs share a draft, storage is full, or a new identity opens cached content: Tasks 7 and 9 must detect conflicts/failure and isolate data.
- A projection write fails after commit, or worker source metadata changes during a render: Tasks 2 and 4 must preserve database authority and prevent stale output from becoming current.

## File map and dependency order

This is one integrated feature: both clients depend on the same state/command/event contract. Do not create independently deployed subsystems or a second specification.

| Unit | Files and responsibility |
| --- | --- |
| Transactional persistence | `dojo-core/src/dojo/live.py` for event/state values; `adapters/db.py`, `adapters/memory.py`, `ports.py` for storage; one new schema revision. |
| Package authority | Existing `publishing.py`, `testing.py`, and a focused `package_state.py` for pure document/merge helpers; filesystem projection remains derived. |
| Command contract | Existing package routes/models, client generation scripts/output, and handwritten HTTP wrappers. |
| Other event producers | Existing setup, pairing, Meta, schedule, publishing, and database mutation paths. |
| SSE delivery | New `backend/src/backend/live.py`, `routes/events.py`; existing lifespan and authentication wiring. |
| Web live coordination | Replace `web/src/live.ts`; adapt `useLiveData.ts`, session/app/provider wiring. |
| Web draft editing | New `packages/drafts.ts`; adapt existing editor/provider/UI, translations, and tests. |
| Android live coordination | New `live/LiveEvents.kt`, `live/LiveCoordinator.kt`; adapt existing API, ViewModel, Activity, and Compose lifecycle wiring. |
| Android drafts | New `editor/DraftStore.kt`; adapt existing editor state/UI. Keep `offline/SnapshotStore.kt` as a server-snapshot cache. |
| Integrated verification | Existing browser/Android acceptance infrastructure plus focused live-state tests and verification notes. |

Dependencies: 1 → 2 → 3; 1–3 → 4 → 5; 3 and 5 → 6 → 7; 3 and 5 → 8 → 9; all → 10. Tasks are executed serially unless the approved execution method explicitly permits otherwise.

### Task 1: Add transactional state and durable invalidation storage

**Files:** Create `dojo-core/src/dojo/live.py`, `dojo-core/migrations/versions/0017_live_state.py`, `dojo-core/tests/test_live_store.py`. Modify `dojo-core/src/dojo/{ports.py,adapters/db.py,adapters/memory.py}`, `dojo-core/tests/test_schema_init.py` (its schema-head assertion currently names revision 0016).

**Interfaces:**
- `PackageState(package_id: int, content_revision: int, view_revision: int, document: dict)`; the document retains the existing manifest shape to reuse current domain calculations.
- `ChangeEvent(event_id: str, versions: dict[str, int], revoked_client_ids: list[int])`; event IDs are UUID strings, not commit-ordered cursors.
- Store methods: `command_transaction() -> AbstractContextManager[None]`, `read_package_state(package_id: int, *, for_update: bool = False) -> PackageState | None`, `write_package_state(package_id: int, document: dict, *, content_changed: bool) -> PackageState`, `record_change(resources: list[str], *, revoked_client_ids: list[int] | None = None) -> ChangeEvent`, `get_change(event_id: str) -> ChangeEvent | None`, `get_resource_version(resource: str) -> int` (zero before the first change).
- A new package-state row has content/view revisions starting at 1. `record_change` advances per-resource versions and notifies channel `dojo_changes` with only the event UUID.

- [ ] **Step 1: Write failing storage tests.** Reuse the existing `pg_store` fixture and second-store pattern from `test_emission_idempotency.py`. Add `test_state_and_event_rollback_together`, `test_notify_after_commit_only`, and `test_memory_nested_command_rollback`. Pin these assertions:
  ```python
  assert other.read_package_state(package.id) is None  # before commit
  assert notifications == []  # before commit and after rollback
  assert other.get_change(event.event_id).versions == {"dashboard": 1}
  assert restored_document == original_document  # nested failure, memory and PostgreSQL
  ```
- [ ] **Step 2: Run** `uv run --project dojo-core pytest dojo-core/tests/test_live_store.py -v`; expect failures for missing interfaces, not unavailable Docker.
- [ ] **Step 3: Implement storage.** Add package-state JSONB, resource-version rows, and durable-event rows to existing metadata/schema conventions. Reuse `emission_transaction()` and its context-bound connection: `command_transaction()` joins an existing outer transaction or owns one, without committing it early. Acquire version-row locks in sorted resource-key order. Parameterize `pg_notify`; failure rolls back state and event. Require an active command transaction for locked reads/writes/events. Mirror rollback behavior in memory, including nested writes. Do not create a second generic unit-of-work framework.
- [ ] **Step 4: Run** the new tests plus `dojo-core/tests/test_emission_idempotency.py`; expect PASS with real PostgreSQL commit/rollback assertions.
- [ ] **Step 5: Commit** only Task 1 files: `feat(core): add transactional live state storage`.

### Task 2: Make PostgreSQL authoritative for the package lifecycle

**Files:** Create `dojo-core/src/dojo/package_state.py`, `dojo-core/tests/test_package_state.py`. Modify `dojo-core/src/dojo/{publishing.py,testing.py}`, `dojo-core/tests/{test_selections.py,test_render.py,test_package_actions.py,test_render_selections.py,test_media_removal.py}`.

**Interfaces:** `DojoPublishing._load_manifest(package: Package) -> dict` reads database state; `_write_manifest(package: Package, manifest: dict) -> None` writes authoritative state within the command transaction. `export_manifest(package: Package) -> None` writes a derived filesystem representation without reading it back as authority. New-package creation initializes the database document. Existing public lifecycle methods retain their roles; HTTP contracts change in Task 3.

- [ ] **Step 1: Write failing tests** `test_database_wins_over_modified_manifest`, `test_missing_projection_does_not_lose_state`, `test_projection_failure_after_commit_is_not_rollback`, and `test_lifecycle_updates_share_state_transaction`. Use existing upload/finalize helpers, updating them to inspect the seam/store instead of editing disk to seed state:
  ```python
  assert seam.get_active_editor()["montage"]["order"] == database_order
  assert store.read_package_state(package.id).document == committed_document
  assert failed_command_state == initial_state
  assert retry_projection_state == committed_document
  ```
- [ ] **Step 2: Run** `uv run --project dojo-core pytest dojo-core/tests/test_package_state.py -v`; expect authority/atomicity failures against current file-backed behavior.
- [ ] **Step 3: Implement authority.** Reuse the existing document format; do not normalize every media property into a new table. Replace authoritative manifest reads/writes across create, upload finalization/replacement, media processing, removal/restore, ordering, selections, caption/branding, render, completion, and cleanup. Keep file moves and derived exports explicitly separate from database commit guarantees. Read-side projection generation must not mutate database revisions. Export committed documents using temporary-file replacement under the existing package lock; report projection failures without erasing committed database state. Existing recovery of physical folders must not reimport stale editable values. Missing state for an old package is an explicit error, not implicit backfill.
- [ ] **Step 4: Run** the files listed above and `dojo-core/tests/test_emission_idempotency.py`; expect PASS. Existing artifact tests may assert exported files, but concurrency tests must inspect authoritative state.
- [ ] **Step 5: Commit:** `feat(core): store package edits in PostgreSQL`.

### Task 3: Add conditional grouped edits and generated HTTP contracts

**Files:** Modify `dojo-core/src/dojo/{package_state.py,publishing.py,exceptions.py,__init__.py}`, `backend/src/backend/routes/{packages.py,package_models.py}`, `backend/scripts/generate_clients.py`, `backend/openapi.json`, `web/src/api/{client.ts,openapi.ts}`, `android/app/src/main/java/com/dojo/aisomedo/api/{DojoApi.kt,GeneratedApi.kt}`. Create `dojo-core/tests/test_package_merge.py`; extend `backend/tests/test_package_editor_api.py` and client contract tests.

**Interfaces:**
- Internal `GroupEdit(key: str, base: dict, proposed: dict)` and `merge_edit_groups(current: dict, changes: list[GroupEdit]) -> dict`; raises `PackageEditConflict` with current conflicting group values.
- `DojoPublishing.apply_package_edits(package_id: int, expected_folder_name: str, base_content_revision: int, changes: list[GroupEdit], requester: str | None = None) -> dict` returns the refreshed editor snapshot.
- `PUT /api/packages/active/edits`: `PackageEditIn(expected_package_id, expected_folder_name, base_content_revision, changes)`; `GroupEditIn(key, base: dict[str, object], proposed: dict[str, object])`. Keys: `video:<media_id>`, `photo:<media_id>`, `order`, `caption`, `branding`. Value shapes respectively: `{ranges: [...]}`, `{seconds: number}`, `{ids: [...]}`, `{text: string | null}`, `{settings: {...}}`. Validate exact keys/types and domain constraints; reject duplicates and unknown groups.
- Editor responses add `content_revision` and `view_revision`. A 409 conflict body is `{detail: {code: "edit_conflict", content_revision, conflicts: [{key, current}]}}`; preserve it through both handwritten API error wrappers.
- Web `api.savePackageEdits(body: PackageEditIn, signal?: AbortSignal): Promise<ActiveEditorOut>`; Android `suspend fun savePackageEdits(body: PackageEditIn): ActiveEditorOut`.

- [ ] **Step 1: Write failing tests** for independent videos, same-video different endpoints, identical proposals, stale package identity, removed media, malformed groups, and full-batch duration rejection. Include concrete merge assertions:
  ```python
  assert result["selections"] == {"a": [{"start": 0, "end": 5}], "b": [{"start": 2, "end": 8}]}
  assert conflict_keys == ["video:a"]
  assert after_rejection == before_command
  assert identical_result.content_revision == before_command.content_revision
  ```
  In duration tests configure a 10-second limit, with two proposed independent six-second selections; neither submitted edit may commit.
- [ ] **Step 2: Run** `uv run --project dojo-core pytest dojo-core/tests/test_package_merge.py -v` and `uv run --project backend pytest backend/tests/test_package_editor_api.py -v`; expect failures for the new command/contract.
- [ ] **Step 3: Implement B/L/S comparison** under the package lock and transaction, then validate the prospective montage before any commit. A no-op emits no duplicate content event or render invalidation. Adapt existing direct mutation routes so none bypass conditional content checks: require the displayed content revision for order/remove/restore/render/clear/caption/branding operations, or route draftable edits through `apply_package_edits`. Keep review version checks. Extend generic JSON-map generation only as needed, mapping object values to TypeScript `unknown` and Kotlin `JsonElement`.
- [ ] **Step 4: Export/regenerate:** `uv run --project backend python backend/scripts/export_openapi.py`, then `uv run --project backend python backend/scripts/generate_clients.py`. Run Task 3 tests and `uv run --project backend pytest backend/tests/test_contract.py -v`; expect PASS and deterministic regenerated output. Update existing fixture DTOs at this task's boundary so client typechecks remain valid.
- [ ] **Step 5: Commit:** `feat(api): add atomic conditional package edits`.

### Task 4: Emit complete view invalidations and fence render completion

**Files:** Modify `dojo-core/src/dojo/{publishing.py,setup.py,pairing.py,meta_connection.py,scheduler.py,adapters/db.py,adapters/memory.py}`, `worker/src/worker/main.py` only at existing command boundaries. Create `dojo-core/tests/test_live_producers.py`, `dojo-core/tests/test_render_revision_fence.py`; extend `worker/tests/{test_worker.py,test_worker_tick.py}` for worker-originated emissions.

**Interfaces:** All producers call Task 1 `record_change` inside the same transaction as their actual state mutation. Resource keys are `package:<id>`, `dashboard`, `setup`, `settings`, `activity`, `completed`, `review:<id>`, `publication`, `upload:<id>`, and `auth`. Read responses expose the relevant committed resource version through `X-Resource-Version`; package snapshots additionally expose Task 3 revisions. Backend routes obtain the data and version in a consistent read boundary.

- [ ] **Step 1: Write failing producer tests** parameterized by package edits, job queued/processing/done/failed, upload finalization, setup/Meta changes, review/publication transitions, and pairing revocation. Assert exact affected resource keys and no event on rollback. Add a blocking stub renderer test:
  ```python
  assert event.versions.keys() >= {"dashboard", f"package:{package.id}"}
  assert event.revoked_client_ids == [revoked.id]
  assert current_content_revision != rendered_content_revision
  assert editor["render_status"] != "ready"  # stale render completed later
  ```
- [ ] **Step 2: Run** `uv run --project dojo-core pytest dojo-core/tests/test_live_producers.py dojo-core/tests/test_render_revision_fence.py -v`; expect missing events/fencing failures.
- [ ] **Step 3: Implement producers.** Put event creation beside authoritative writes, not merely audit appends or HTTP route returns. Read/claim/work/completion transactions must be short; FFmpeg and external publication requests remain outside them. Pass an immutable state snapshot/revision to rendering, and conditionally attach output on completion. Content-affecting source metadata changes also invalidate matching render input. Preserve uncertain-publication protections. Build a write-path coverage table in the producer test module using actual mutations; every displayed view in the spec must have a producer. Do not claim worker process death is a committed status transition.
- [ ] **Step 4: Run** Task 4 tests plus existing scheduling, render, review, setup, pairing, and worker tests; expect PASS without duplicate emissions under scheduler contention.
- [ ] **Step 5: Commit:** `feat(core): emit committed state invalidations`.

### Task 5: Serve authenticated, bounded SSE from PostgreSQL notifications

**Files:** Create `backend/src/backend/live.py`, `backend/src/backend/routes/events.py`, `backend/tests/test_live_events.py`. Modify `backend/src/backend/{main.py,deps.py}`, `backend/src/backend/routes/{dashboard.py,setup.py,activity.py,settings.py,packages.py,reviews.py,publication.py,media.py}` for Task 4 version headers, and `dojo-core/src/dojo/{pairing.py,adapters/db.py}` to expose the existing session authorization deadline without credentials. Regenerate OpenAPI if read response contracts change.

**Interfaces:** In `backend/live.py`, define `StreamMessage(event: str, data: dict)` and `LiveHub.start() -> Awaitable[None]`, `LiveHub.close() -> Awaitable[None]`, `LiveHub.subscribe(client_id: int, *, expires_at: datetime | None) -> AsyncIterator[StreamMessage]`. `GET /api/events` uses existing session/bearer authentication. Stream types: `ready` with `{protocol: 1}`, `change` with `{event_id, versions}`, `resync` with `{reason}`, and `heartbeat` with `{}`. Revocations and explicit session invalidations close that client's existing streams; unaffected valid sessions may authenticate again. Consume these signals server-side, not as identity details broadcast to all clients.

- [ ] **Step 1: Write failing async tests** with real PostgreSQL plus injectable clock/connection loss. Assert commit-before-ready listener setup, changes during subscription, one listener for ten subscribers, heartbeat without SQL, stream shutdown on listener loss, bounded overflow, expiration, revocation, and unauthorized establishment:
  ```python
  assert first.event == "ready"
  assert listener_connection_count == 1
  assert idle_sql_count_after_ready == 0
  assert events_at_15_seconds == ["heartbeat"]
  assert revoked_stream_closed and unaffected_stream_open
  ```
  Test a 64-message client queue overflow and a missing durable-event lookup: both must force resynchronization, never silently discard a change.
- [ ] **Step 2: Run** `uv run --project backend pytest backend/tests/test_live_events.py -v`; expect missing endpoint/lifecycle behavior.
- [ ] **Step 3: Implement the hub** with existing Psycopg 3 notifications (locked version 3.3.4) on one dedicated autocommit connection, consuming either its notification generator or handler, never both. Commit `LISTEN dojo_changes` before readiness. Convert the existing SQLAlchemy URL to driver connection parameters without logging credentials. Register subscribers before ready; event-triggered lookup/fanout has bounded queues. Perform event lookup using the store, not by issuing queries concurrently on the listener connection; offload synchronous database work from the event loop. Use 15-second heartbeat events, event-loop deadline timers for session expiry, and connection-level heartbeat/failure detection rather than periodic SQL checks. Listener failure closes all dependent streams; reconnect only restores readiness after LISTEN succeeds. Use Starlette streaming responses with no buffering/cache headers, cancellation cleanup, and merged authentication response headers so browser session renewal is not lost. Respect existing Android version rejection. No extra SSE dependency.
- [ ] **Step 4: Run** Task 5 tests plus backend authentication/contract tests; expect PASS. Test streaming against a real local ASGI server when the test client's response buffering would otherwise hide disconnect behavior.
- [ ] **Step 5: Commit:** `feat(api): stream authenticated live invalidations`.

### Task 6: Replace web polling with a shared live coordinator

**Files:** Replace `web/src/live.ts`; modify `web/src/{useLiveData.ts,session.tsx,App.tsx}`, `web/src/api/client.ts`, and `web/src/packages/PackageEditorProvider.tsx`. Create `web/src/liveProvider.tsx`, `web/src/useLiveData.test.tsx`; extend `web/src/live.test.ts` and affected consumer tests.

**Interfaces:** Export `LivePhase = "connecting" | "syncing" | "live" | "disconnected" | "unauthorized"`; `startLiveRefresh(refresh: (signal: AbortSignal) => Promise<void>, resources: readonly string[]): () => void` preserves consumer cleanup while subscribing to the coordinator instead of an interval. `useLiveData(load, enabled, resources)` uses explicit affected resource keys. The root `LiveProvider` owns one foreground Fetch stream and exposes phase/synchronization state. HTTP reads internally retain `X-Resource-Version` without breaking existing body-only API callers.

- [ ] **Step 1: Write failing tests** `idleHeartbeatDoesNotReadData`, `invalidationDuringReadRunsOneFollowup`, `olderResponseCannotReplaceNewerState`, `heartbeatDeadlineLocksAt45Seconds`, and `streamFramesSurviveUtf8AndCrLfSplits`. Use fake timers and controlled streams:
  ```typescript
  expect(readsAfterTenMinutesOfHeartbeats).toBe(readsAfterInitialSync);
  expect(maxConcurrentReads).toBe(1);
  expect(readCountAfterBurstDuringRead).toBe(2);
  expect(phaseAt45001msWithoutTraffic).toBe("disconnected");
  ```
  Include multiline `data`, split UTF-8, EOF mid-frame, unknown event types, wrong content type, 401/426, and frames exceeding 64 KiB; malformed required protocol data cannot unlock editing.
- [ ] **Step 2: Run** `npm --prefix web test -- src/live.test.ts src/useLiveData.test.tsx`; expect current polling and missing parser/coordinator failures.
- [ ] **Step 3: Implement Fetch streaming** with incremental `TextDecoder`, line/frame buffering, AbortController cleanup, heartbeat observation, and one reconnect owner with 1–30-second jittered backoff. Route changes to explicit resource subscribers. Synchronization uses pending invalidation markers and monotonic per-resource versions; a read failure remains locked until an event/reconnect/manual retry succeeds. A hidden tab stops its stream and becomes unsynchronized; foreground return resubscribes before reading. Replace every `startLiveRefresh` caller with an explicit resource list, including active editor and upload status views. Do not change upload-transfer retries or OAuth user-triggered attempt behavior into general polling.
- [ ] **Step 4: Run** `npm --prefix web test` and `npm --prefix web run typecheck`; expect PASS. Assert no repeated foreground state reads over fake ten-minute idle periods; transport timers remain allowed.
- [ ] **Step 5: Commit:** `feat(web): replace live polling with SSE`.

### Task 7: Persist web drafts and expose safe conflict resolution

**Files:** Create `web/src/packages/{drafts.ts,drafts.test.ts}`. Modify `web/src/packages/{usePackageEditor.ts,usePackageEditor.test.tsx,PackageEditorProvider.tsx,ActivePackagePanel.tsx,VideoSectionEditor.tsx}`, `web/src/{session.tsx,i18n/tr.ts}` and mutation controls in `components/`, `reviews/`, `onboarding/` that must obey the live gate.

**Interfaces:** `DraftKey = {origin: string; clientId: number; packageId: number}`; `StoredDraft = {schemaVersion: 1; localRevision: number; folderName: string; baseContentRevision: number; groups: Record<string, {base: Record<string, unknown>; proposed: Record<string, unknown>}>; inputs: Record<string, RangeInput[]>; uncertain: boolean}`. `readDraft(key: DraftKey): Promise<StoredDraft | null>`, `writeDraft(key: DraftKey, expectedLocalRevision: number, draft: StoredDraft): Promise<number>`, `deleteDraft(key: DraftKey, expectedLocalRevision: number): Promise<void>`. Revision zero means no existing draft; successful writes increment it. IndexedDB transactions perform compare-and-replace atomically. Expose editor `canEdit: boolean`, `resolveConflict(key: string, choice: "server" | "local"): void`, and persistence/connection errors through the existing provider.

- [ ] **Step 1: Write failing tests** for reload, incomplete input, identity separation, competing-tab CAS, quota errors, package completion, and lost save response:
  ```typescript
  expect(reopened.draftInputs.a[0].end).toBe("");
  expect(reopened.canEditBeforeSync).toBe(false);
  expect(otherClientDraft).toBeNull();
  await expect(secondTabWrite).rejects.toThrow("draft_conflict");
  expect(mutationCountAfterUncertainReload).toBe(1);
  ```
  Add real-browser IndexedDB tests in Task 10; Vitest unit tests can use an injected in-memory storage boundary, not a new mocking dependency.
- [ ] **Step 2: Run** `npm --prefix web test -- src/packages/drafts.test.ts src/packages/usePackageEditor.test.tsx`; expect persistence/gating failures.
- [ ] **Step 3: Implement drafts and reconciliation.** Persist edits while typing, including incomplete strings; preserve the last durable version on replacement failure. Restore read-only, then reconcile baseline/local/server groups through Task 3 semantics. Disable field changes, dragging, remove/restore/render/save and other state-changing controls whenever not synchronized. Conflicts preserve input and offer explicit local/server choices, followed by a new conditional command. Persist uncertainty before sending a mutation and clear acknowledged groups only after a confirmed/reconciled result. Do not let follow-up snapshots reset unresolved baselines or clear another tab's draft. Clear the identity's drafts on explicit unpair; quarantine invalid/unsupported drafts with visible recovery failure rather than silent deletion.
- [ ] **Step 4: Run** web tests and typecheck; expect PASS. Include root component tests proving disabled controls cannot mutate through keyboard, drag, or direct handlers while disconnected, and storage failure is visibly reported without claiming recoverability.
- [ ] **Step 5: Commit:** `feat(web): preserve drafts and resolve edit conflicts`.

### Task 8: Add foreground Android SSE and remove review polling

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/live/{LiveEvents.kt,LiveCoordinator.kt}` and corresponding tests under `android/app/src/test/java/com/dojo/aisomedo/live/`. Modify `api/DojoApi.kt`, `AppViewModel.kt`, `MainActivity.kt`, `ui/DojoApp.kt` under the existing Android package and their existing tests.

**Interfaces:** In `LiveEvents.kt`, define `LiveEvent(type: String, protocol: Int? = null, eventId: String? = null, versions: Map<String, Long> = emptyMap(), reason: String? = null)` matching Task 5 wire fields. `enum class LivePhase { CONNECTING, SYNCING, LIVE, DISCONNECTED, UNAUTHORIZED }`; `DojoApi.liveEvents(): Flow<LiveEvent>` emits messages using existing bearer/version headers. `LiveCoordinator.phase: StateFlow<LivePhase>`, `setForeground(active: Boolean)`, `invalidate(resources: Set<String>)`, `stop()`. ViewModel coordinates one in-flight read and pending refresh marker per active resource and exposes live readiness to UI admission checks.

- [ ] **Step 1: Write failing JUnit/MockWebServer tests** `heartbeatsDoNotPoll`, `streamSurvivesFragmentedFrames`, `disconnectLocksUntilResync`, `invalidationDuringReadIsNotLost`, and `unauthorizedStreamStopsReconnect`. Assert:
  ```kotlin
  assertEquals(initialDataReads, dataReadsAfterTenMinutes)
  assertEquals(LivePhase.DISCONNECTED, phaseAfter45SecondsWithoutTraffic)
  assertEquals(1, maximumConcurrentResourceReads)
  assertFalse(editorCanMutateBeforeResync)
  ```
  Match Task 6 UTF-8/CRLF/multiline/64-KiB frame cases and test stream cancellation during a blocked socket read.
- [ ] **Step 2: Run** `android\gradlew.bat -p android :app:testDebugUnitTest --tests "com.dojo.aisomedo.live.*"`; expect missing coordinator/stream behavior, not environment failures.
- [ ] **Step 3: Implement streaming with installed OkHttp**, not a new SSE library. Give only the stream client an unlimited overall call deadline and a 45-second idle-read deadline; preserve ordinary request/upload/publication timeouts and no-replay mutation behavior. Read frames on IO dispatchers, cancel the Call/body on coroutine cancellation, and back off 1–30 seconds with jitter. Start/stop through existing foreground lifecycle; network availability alone cannot unlock writes. Remove the five-second `pollReview()` loop in `ui/DojoApp.kt`; keep the method only if renamed/routed as an event-triggered refresh with no timer caller. Do not use `DojoApi.request()` GET retry loops for streaming or as periodic data retries.
- [ ] **Step 4: Run** new live tests and existing `AppViewModelTest`, `OfflineAppViewModelTest`, and API unit tests via `:app:testDebugUnitTest`; expect PASS. Preserve existing push registration/background upload behavior unchanged.
- [ ] **Step 5: Commit:** `feat(android): synchronize foreground state over SSE`.

### Task 9: Restore Android drafts without weakening live admission

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/editor/DraftStore.kt`, `android/app/src/test/java/com/dojo/aisomedo/editor/DraftStoreTest.kt`. Modify `editor/MediaEditorState.kt`, `AppViewModel.kt`, `ui/{MediaEditorPanel.kt,DojoApp.kt}`, relevant localized resources, and `editor/MediaEditorTest.kt`. Keep server snapshot caching in `offline/SnapshotStore.kt`; do not put drafts into its credential-free server-snapshot DTO.

**Interfaces:** `@Serializable data class StoredDraft` mirrors Task 7 semantic fields using Kotlin DTOs/JsonElement and existing `RangeInput`; `DraftStore.read(origin: String, bindingId: String, packageId: Int): StoredDraft?`, `DraftStore.write(origin: String, bindingId: String, packageId: Int, draft: StoredDraft)`, `DraftStore.clear(origin: String, bindingId: String, packageId: Int)`. Reuse the normalized origin and hashed binding identity from existing auth/cache code; never embed bearer credentials in paths or content.

- [ ] **Step 1: Write failing tests** `reopenPreservesIncompleteDraft`, `failedReplacementPreservesPreviousDraft`, `otherBindingCannotRestore`, `uncertainWriteDoesNotReplay`, and `completionKeepsDraftReadOnly`:
  ```kotlin
  assertEquals("", reopened.inputs.getValue("a")[0].end)
  assertEquals(previous, readAfterFailedReplacement)
  assertNull(otherBindingDraft)
  assertEquals(1, mutationRequestCountAfterRecovery)
  assertFalse(completedPackageDraft.canSave)
  ```
- [ ] **Step 2: Run** `android\gradlew.bat -p android :app:testDebugUnitTest --tests "com.dojo.aisomedo.editor.*"`; expect missing durable recovery behavior.
- [ ] **Step 3: Implement app-private atomic replacement** using the existing snapshot store's temporary-file, fsync, and atomic-move pattern without extracting an unnecessary generic persistence framework. Serialize writes in input order and protect newer input from late write acknowledgments. Persist incomplete edits and uncertainty; restore read-only before authenticated synchronization. Reconcile by Task 3 group rules and save explicitly. All edit handlers, draft discard/conflict resolution, and mutations must honor the live gate. Retain drafts on recoverable network failures, isolate identities, clear on explicit unpair, and show corrupted/storage-failure states rather than silently clearing data.
- [ ] **Step 4: Run** all Android debug unit tests; expect PASS. Add Compose assertions that disconnected fields/drag handles/actions are disabled and restoration never briefly enables editing before sync.
- [ ] **Step 5: Commit:** `feat(android): persist and reconcile editor drafts`.

### Task 10: Prove cross-process behavior and document verification

**Files:** Create `web/e2e/live-state.spec.ts` for deterministic browser/storage tests, `web/acceptance/live-state.spec.ts` for real-stack behavior, `backend/tests/test_live_integration.py`, `android/app/src/androidTest/java/com/dojo/aisomedo/ui/LiveStateTest.kt`, `docs/verification/live-state-sse.md`. Reuse `web/playwright.config.ts` (`e2e`) and `web/playwright.acceptance.config.ts` (`acceptance`) without changing their test directories; follow `web/acceptance/publication.spec.ts` and existing isolated stack fixtures. Update `README.md` behavior notes without adding a deployment/transition plan.

**Interfaces:** Consume Tasks 1–9 as public HTTP/client behavior. Test fixtures may inject an isolated clock, stub renderer, or PostgreSQL disconnect; no production-only test endpoint and no real Instagram publication.

- [ ] **Step 1: Write failing integration scenarios**: two independent backend processes observe one worker mutation; two browser contexts merge distinct videos but reject same-video conflicts atomically; real IndexedDB survives reload; one context's stream interruption locks fields and retains draft; Android restart restores read-only draft; revocation closes an already-open connection; burst invalidation and listener reconnect converge to current state. Assert network request counts rather than merely searching for `setInterval`.
- [ ] **Step 2: Run** `uv run --project backend pytest backend/tests/test_live_integration.py -v`, `npm --prefix web run test:browser -- live-state.spec.ts`, and `android\gradlew.bat -p android :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.LiveStateTest`. Within the existing isolated acceptance environment, run `npm --prefix web run test:acceptance -- live-state.spec.ts`; that configuration requires its configured base URL and evidence mount. Record genuine failures and environment blockers separately.
- [ ] **Step 3: Fix only integration seams** exposed by these tests. Verify SSE flush/no-cache behavior through the existing local hosting/proxy path; adapt its config only if buffering blocks events. Confirm no frontend state-read timer or server event-table scan was introduced. Do not change unrelated worker/upload timers to make this assertion pass.
- [ ] **Step 4: Run final checks** from the repository root:
  ```powershell
  uv run --project dojo-core pytest dojo-core/tests -q
  uv run --project backend pytest backend/tests -q
  uv run --project worker pytest worker/tests -q
  uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
  uv run --project backend ruff check backend/src backend/tests
  uv run --project worker ruff check worker/src worker/tests
  uv run --project dojo-core mypy dojo-core/src/dojo
  uv run --project backend mypy backend/src/backend
  uv run --project worker mypy worker/src/worker
  npm --prefix web test
  npm --prefix web run build
  android\gradlew.bat -p android :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
  ```
  Rerun Task 3 generation and confirm generated files are unchanged. Run browser and connected-device checks from Step 2; missing Docker, FFmpeg, JDK/SDK, or device means blocked verification, not PASS. Record commands, outcomes, and any blockers in `docs/verification/live-state-sse.md`.
- [ ] **Step 5: Commit:** `test: verify cross-platform live synchronization`.

## Plan self-review and execution gate

- [x] Spec coverage: Sections 1–3 → constraints/file map; 4–6 → Tasks 1–5; 7–8 → Tasks 5–8; 9 → Tasks 7/9; 10 → Tasks 2/4; 11 → Tasks 4–6/8/10; 12 → all test cycles and Task 10.
- [x] Type consistency: one group-edit contract, one event resource-key vocabulary, one shared transport protocol; each platform retains native storage/lifecycle adapters.
- [x] Review Focus cases assigned concrete tests; no background polling fallback or data-transition task.
- [x] Steps specify files, interfaces, checks, and commit boundaries without prescribing full implementation bodies.
- [ ] User reviews this plan and selects execution method.
- [ ] Before implementation, load the selected execution skill and establish an isolated worktree through the worktree skill.

Recommended execution: **Native**, with one final independent review. The shared transaction/event/API interfaces form a dependency chain; one implementer avoids repeated cross-task context setup while the plan supplies focused test gates. Subagent-driven execution remains available if separate implementation/review contexts per task are preferred.

No implementation or test-pass claim is made by this plan. Do not execute Task 1 until the user approves the plan and chooses the execution method.
