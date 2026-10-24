# Active Package Media Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver independent media-card editing, cancellable saved-section previews, and correctly scheduled Reel previews on web and Android.

**Architecture:** Extend the existing grouped edit command, PostgreSQL package document, job store, authenticated artifact routes, and SSE invalidations. Preview metadata remains derived view state, while render inputs remain content. A shared worker pipeline uses per-media generation fencing and actual subprocess cancellation.

**Tech Stack:** Existing Python/FastAPI/PostgreSQL/FFmpeg, React/TypeScript, Kotlin/Compose, pytest, Vitest, Playwright, and Android tests; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-24-active-package-media-panel-design.md`

## Global Constraints

- Selected intervals describe retained footage, not footage to remove.
- No selected intervals means the whole video participates in the montage.
- Retain the existing minimum duration of one frame at 25 FPS.
- Ordinary media edits alone must not automatically request a Reel.
- A due Yayın Zamanı automatically requests a current Reel for Yayın İncelemesi.
- Publication still requires explicit user approval; drafts never enter server-side renders.
- Preview progress and artifact attachment update derived view state and existing live invalidations, not content revision.
- Reuse the current SSE invalidation/snapshot-refresh mechanism; do not add periodic client data polling.
- Preserve existing live-connectivity restrictions, private artifact access, merge behavior, and durable drafts.
- Exact photo label: `Gösterilme süresi (sn)`; remove `Kaydedilecek değişiklik yok.`
- Missing Reel title duration: `Henüz render edilmedi`; missing-preview body: `Kaydedilmiş montajı henüz render edilmedi.`
- No new services, queue brokers, frameworks, destructive data resets, or unrelated refactors.

## Review Focus

1. A-to-B-to-A selections: an old identical-input job must not attach to a newer request (Task 4).
2. Cancellation and encoder stderr saturation: terminate/reap subprocesses without deadlock or turning cancellation into failure (Tasks 3–4).
3. Lost save/removal responses: preserve drafts until server reconciliation proves success; never replay a write implicitly (Tasks 7 and 9).
4. Original and normalized durations differ, including non-millisecond endings: endpoints remain within the authoritative bound (Tasks 8 and 10).
5. Missing old thumbnails and interrupted processing: requests stay bounded, media remains usable, and retry fences abandoned generations (Tasks 4–5).

---

## File map and execution rules

Existing ownership remains: `publishing.py` orchestrates domain transactions; `adapters/db.py` and `memory.py` persist jobs; `adapters/render.py` runs encoding; `package_media.py` allowlists files. Add only focused preview subprocess utilities in `dojo-core/src/dojo/adapters/preview_process.py`, rather than embedding another process-control loop in every encoding method.

Backend contract changes belong in `routes/package_models.py` and `routes/packages.py`, followed by the existing exporters. Web state remains in `usePackageEditor.ts`; extract only the separate Reel panel and fullscreen viewer. Android state remains in `MediaEditorState.kt`/`AppViewModel.kt`; add focused timeline, viewer, and saved-Reel composables.

Run Python commands from repository root; web commands from `web`; Gradle commands from `android` (`.\gradlew.bat` on Windows, `./gradlew` elsewhere). Do not install or provision external infrastructure without authorization. PostgreSQL integration tests use the existing Docker fixture. Report unavailable Docker, FFmpeg, SDK, browser, or emulator checks as blocked, not passed.

At execution start, use the worktree skill and inspect current changes before editing. No product code is authorized until the user approves this plan and selects execution method. Tasks 1–6 establish server contracts; Tasks 7–10 consume them. Existing tests that assume every next queued job is a Reel must explicitly select/drain jobs by kind after preview jobs are introduced; do not hide new jobs by weakening production claims.

Each task follows red → green → commit. Stage only that task's files with explicit paths; never `git add .`. Stop for a design change if a task requires behavior outside the approved spec.

### Task 1: Durable cancellation and preview-job uniqueness

**Files:** Modify `dojo-core/src/dojo/ports.py`, `dojo-core/src/dojo/adapters/db.py`, `dojo-core/src/dojo/adapters/memory.py`; create `dojo-core/migrations/versions/0021_media_preview_jobs.py`; test `dojo-core/tests/test_store_jobs.py`, `test_schema_init.py`, `test_live_store.py`.

**Interfaces:** Extend `JobStore.create_job_once(job: Job, *, audit: AuditEvent | None = None) -> tuple[Job, bool]` to recognize `section_preview` and `thumbnail`. Add `cancel_media_jobs(package_id: int, media_id: str | None, *, kinds: tuple[str, ...], cancelled_at: datetime) -> int` and `finish_if_processing(job_id: str, *, status: str, finished_at: datetime, error_reason: str | None = None) -> Job | None`. `None` means a deleted, cancelled, or otherwise terminal job was not overwritten.

- [ ] **1. Write store tests:** in memory and real PostgreSQL, duplicate active preview requests return the existing job; cancelling A does not cancel B; cancelled jobs are not claimed; completion cannot overwrite cancellation; transaction rollback leaves no job/audit/event. Representative assertions:
  ```python
  assert store.get(a.job_id).status == "cancelled"
  assert store.get(b.job_id).status == "queued"
  assert store.finish_if_processing(a.job_id, status="done", finished_at=FIXED_AT) is None
  ```
- [ ] **2. Run red:** `uv run --project dojo-core pytest dojo-core/tests/test_store_jobs.py -v`; new tests fail because operations/deduplication do not exist.
- [ ] **3. Implement:** job payloads use `package_id`, `package`, `media_id`, and `input_digest`; generation is `job_id`. Add a partial unique index on `(kind, payload ->> 'package_id', payload ->> 'media_id')` for the two new kinds with `status IN ('queued','processing')`. Preserve the existing render index and deduplication. Cancellation is terminal `cancelled`; conditional finishes are atomic updates. All writes join existing command/event transactions. Migration parent is current head `0020_schedule_uniqueness`; verify head before creating the file, without rewriting an externally added migration.
- [ ] **4. Run green:** the store tests plus `uv run --project dojo-core pytest dojo-core/tests/test_schema_init.py dojo-core/tests/test_live_store.py -v`; all pass, including real PostgreSQL index and rollback checks.
- [ ] **5. Commit:** `feat: add cancellable media preview jobs`.

### Task 2: Transactional per-video preview lifecycle

**Files:** Modify `dojo-core/src/dojo/publishing.py` (`_write_manifest`, `apply_package_edits`, `_save_selections`, media lifecycle commands); create `dojo-core/tests/test_section_previews.py`; extend `test_package_merge.py`, `test_media_removal.py`, `test_live_producers.py`.

**Interfaces:** Consume Task 1 job methods. Add `DojoPublishing.retry_section_preview(media_id: str, *, expected_package_id: int, expected_folder_name: str, expected_generation: str) -> dict`. Derived document maps are `section_previews` and `thumbnails`, keyed by media ID. Section records contain `generation`, `input_digest`, `status`, `artifact_ref`, `duration`, and nullable `retry_of`; non-ready artifact/duration values are null. Job payload additionally captures normalized `ranges` and `source_identity`.

- [ ] **1. Write lifecycle tests:** changed selection commits exactly one current generation; identical save adds none; empty selection cancels work and removes the record; photo/reorder edits preserve it; failed validation rolls back edits/jobs. Assert:
  ```python
  assert after.document["section_previews"][mid]["generation"] != old_generation
  assert old_job.status == "cancelled"
  assert after.content_revision == before.content_revision + 1
  ```
  Fetch `old_job` again after the command. Add derived-only update assertions: `view_revision` advances, `content_revision` and `_render_digest` do not. Parameterize grouped edits, legacy selections, and legacy trims. Confirm removal/clear/replacement cancel work, and restore requests a preview for nonempty persisted sections without resurrecting drafts.
- [ ] **2. Run red:** `uv run --project dojo-core pytest dojo-core/tests/test_section_previews.py dojo-core/tests/test_package_merge.py -v`.
- [ ] **3. Implement:** reconcile old/new persisted media eligibility, source identity, and normalized ranges at the shared transactional document write boundary. Source identity uses immutable media ID, upload identity/date, and processed path/size/duration; metadata-only preview changes must not feed back into scheduling. Generate a fresh UUID per changed request, cancel before enqueue, and keep derived maps outside `content_fields()`. No filesystem deletion before command commit. Retry validates expected package/generation; a replacement records `retry_of=expected_generation`, so duplicated retries of that failed generation reuse the current equivalent active job. A request for any other stale generation is a conflict; empty selection has nothing to retry. Cover duplicate retry after a lost response explicitly.
- [ ] **4. Run green:** lifecycle/merge/removal/live-producer tests pass; repeat identical writes and inspect job/audit counts to prove idempotence. Update old tests' explicit job-kind expectations without changing production queue order.
- [ ] **5. Commit:** `feat: schedule card-local section previews`.

### Task 3: Cancellable encoding primitives and real output verification

**Files:** Create `dojo-core/src/dojo/adapters/preview_process.py`, `dojo-core/tests/test_preview_process.py`, `dojo-core/tests/test_preview_encoding.py`; modify `adapters/render.py`, `adapters/stubs.py`, `ports.py`, and `dojo-core/tests/ffmpeg_transport.py` only where needed for subprocess-capable transport.

**Interfaces:** Add `run_preview_process(args: list[str], *, cancelled: Callable[[], bool], timeout_seconds: float = 900.0) -> str`, returning decoded stdout for small probe results and raising `PreviewCancelled` or `RenderFailed`; define `PreviewCancelled` in the same focused module. Extend existing `ReelRenderer`/real and stub renderers with `render_sections(clips: list[ReelClip], work_dir: Path, out_path: Path, *, cancelled: Callable[[], bool]) -> Path`, `render_thumbnail(source: Path, out_path: Path, *, cancelled: Callable[[], bool]) -> Path`, and `probe_duration(path: Path, *, cancelled: Callable[[], bool]) -> float`.

- [ ] **1. Write process and encoding tests:** real controllable Python child process is terminated and reaped on cancellation; kill escalation works; a large stderr producer cannot deadlock; cancellation callback exceptions fail closed; timeout stops work. Test no-audio input and chronological selections on the existing red/green/blue synthetic fixture with distinct audio frequencies:
  ```python
  assert child.poll() is not None
  assert abs(measured_duration - expected_duration) <= 1 / 25 + 0.05
  ```
  Decode sample frames/audio to prove first/last sections, not just duration or command construction. Verify no logo/intro/outro in section output and no source mutation.
- [ ] **2. Run red:** `uv run --project dojo-core pytest dojo-core/tests/test_preview_process.py dojo-core/tests/test_preview_encoding.py -v`.
- [ ] **3. Implement:** use `Popen` with stdout/stderr redirected to temporary files, read only a bounded stderr tail for failures, and return small decoded probe stdout. Check cancellation every 0.25 seconds; terminate, allow 2 seconds, then kill/wait. The 900-second hard deadline covers the entire preview job across all probes, segments, and concatenation, not a fresh budget for each subprocess; Task 4's callback enforces the shared deadline and the helper always reaps on callback exceptions. Reject non-finite/nonpositive probed duration. Reuse existing segment/concat code with an optional cancellation callback, including audio probes; keep ordinary Reel `render()` signature unchanged. Provide real Docker start/stop/wait test transport when native FFmpeg is unavailable, preserving `FfmpegTransport.run` callers. Do not mock away actual encoder execution in output tests.
- [ ] **4. Run green:** process tests and actual encoder tests pass; skipped Docker/FFmpeg tests are a blocker for the real-output acceptance claim, not evidence of correctness. Run `test_render.py` and `test_render_selections.py` to preserve existing Reel behavior.
- [ ] **5. Commit:** `feat: add cancellable preview encoding`.

### Task 4: Worker execution, fencing, thumbnails, and abandoned work

**Files:** Modify `dojo-core/src/dojo/publishing.py` (`process_job`, worker preview handlers, `evaluate_due_work`, upload finalization); extend `dojo-core/tests/test_section_previews.py`, create `dojo-core/tests/test_preview_worker.py`; modify `worker/tests/test_worker_tick.py` and `test_worker.py` for new job kinds/outcomes.

**Interfaces:** Consume Tasks 1–3. Add `_process_section_preview_job(job: Job) -> None`, `_process_thumbnail_job(job: Job) -> None`, and `_maintain_media_preview_jobs() -> None` on `DojoPublishing`. The existing worker calls these via `process_job`/`evaluate_due_work`; no additional worker service or client polling. Preview and thumbnail job kinds never enter upload-failure handling.

- [ ] **1. Write worker races:** A→B→A rejects first A; encode completion racing with removal, replacement, package clear/completion, cancellation, and renderer failure cannot revive output/status. Another card edit/reorder leaves A eligible. Assert:
  ```python
  assert store.get(first_a.job_id).status == "cancelled"
  assert state.document["section_previews"][mid]["generation"] == latest_a.job_id
  assert not old_output_is_current
  ```
  Test separate media concurrently, a lost cancellation-control DB read, missing-thumbnail backfill deduplication, thumbnail failure preserving finalized media, and recovery after interrupted worker execution.
- [ ] **2. Run red:** `uv run --project dojo-core pytest dojo-core/tests/test_preview_worker.py dojo-core/tests/test_section_previews.py -v`; separately `uv run --project worker pytest worker/tests/test_worker_tick.py -v`.
- [ ] **3. Implement:** capture immutable input under lock, encode without it into `media_root/tmp/section-preview-<job_id>`, then re-lock/re-read current package, media, source identity, selection, and generation. Attach generation-specific artifact only if still current; finish conditionally. Cancelled/obsolete jobs clean only owned staging files. Store probe results and events as derived state. Thumbnail output is a reusable JPEG, maximum edge 640 pixels, generated from normalized input; schedule new-upload thumbnails and deduplicated missing-thumbnail work during existing worker maintenance, never by downloading videos to list cards. For existing active videos with nonempty saved selections and no preview record, maintenance requests their first section generation once; failed records are not retried every tick. Run media maintenance before the publication-setup readiness gate, so previews do not require a configured logo or a due schedule. Add tests for existing selected media and incomplete publication setup.
- [ ] **4. Implement bounded recovery:** compare processing `claimed_at` against the 900-second deadline plus 5-second grace; maintenance marks expired current jobs failed via conditional finish. The worker cancellation callback enforces the same whole-job deadline and aborts on an unavailable control check; timeout is failure, supersession is cancellation. Retry fences the expired generation before enqueueing a replacement. Use a fake clock in recovery tests, not a 15-minute sleep. Failed thumbnails show a placeholder and are not re-enqueued every tick; do not add a separate thumbnail retry UI/API in this feature. Keep job cancellation out of failure alerts.
- [ ] **5. Run green:** core preview/worker tests, `test_live_producers.py`, `test_package_actions.py`, `test_media_removal.py`, and worker tests pass, including cancellation during an actual subprocess. Verify derived completion never changes content revision or invalidates the Reel.
- [ ] **6. Commit:** `feat: execute fenced media preview jobs`.

### Task 5: Private artifacts, API models, and generated contracts

**Files:** Modify `dojo-core/src/dojo/package_media.py`, `dojo-core/src/dojo/publishing.py` (editor/preview reads); `backend/src/backend/routes/package_models.py`, `routes/packages.py`, `backend/scripts/generate_clients.py`; regenerate `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`; create `backend/tests/test_media_preview_api.py`; extend `test_contract.py`, `test_client_generation.py`, `dojo-core/tests/test_package_editor.py`.

**Interfaces:** Add `SectionPreviewOut(status: Literal['missing','queued','processing','ready','failed'], generation: str | None, url: str | None, duration: float | None)` and `SectionPreviewRetryIn(expected_package_id: int, expected_folder_name: str, expected_generation: str)`. Preview defaults are `status='missing'` and null generation/URL/duration. Extend `EditorMediaOut` with optional `original_url`, `thumbnail_url`, and `section_preview`; extend `ActiveEditorOut` with nullable `render_duration`. Existing `preview_url` retains its processed/full-source meaning. New authenticated routes under `/api/packages/active/media/{media_id}`: `GET /original`, `GET /thumbnail`, `GET /sections/preview`, `POST /sections/retry`. Reads identify expected package ID/folder; section reads also require generation. Retry returns refreshed `ActiveEditorOut`.

- [ ] **1. Write API tests:** exact original bytes/MIME; current JPEG and section MP4; `Range` produces 206; absent authentication, traversal, wrong package, removed media, and stale generation cannot expose files. Duplicate retry reuses active job; stale retry returns 409; read has no job-creation side effect. Assert:
  ```python
  assert ranged.status_code == 206
  assert stale.status_code == 404
  assert editor["media"][0]["preview_url"] != editor["media"][0]["original_url"]
  ```
  Existing snapshots missing derived fields decode with defaults; thumbnail absent/failure still yields a usable editor. Add generator closure tests for nested nullable status DTOs.
- [ ] **2. Run red:** `uv run --project backend pytest backend/tests/test_media_preview_api.py backend/tests/test_contract.py backend/tests/test_client_generation.py -v`.
- [ ] **3. Implement:** extend manifest allowlisting for derived artifact references with strict current-generation checks and contained paths. Reuse `_file`, session/bearer authentication, safe response headers, and revision-aware URL creation. Keep originals/processed artifacts backward compatible. GET endpoints do not enqueue work. Ensure generator root lists include `SectionPreviewRetryIn`, `ClearPackageIn`, and `ClearPackageOut` for both clients, including Android's newly needed clear command. Regenerate via `uv run --project backend python backend/scripts/export_openapi.py` then `uv run --project backend python backend/scripts/generate_clients.py`; never hand-edit generated DTOs.
- [ ] **4. Run green:** API/contract/generator tests and `test_package_editor_api.py` pass; repeat both generation commands and prove zero second-run output drift with file hashes. Run existing OpenAPI compatibility tests.
- [ ] **5. Commit:** `feat: expose private media preview contracts`.

### Task 6: Reel duration and due-only automatic rendering

**Files:** Modify `dojo-core/src/dojo/publishing.py` (`_ensure_reviews_for_due`, `_render_job`, `get_active_editor`); extend `dojo-core/tests/test_review.py`, `test_empty_occurrence.py`, `test_render_revision_fence.py`, `test_render_selections.py`, and `worker/tests/test_worker_tick.py`.

**Interfaces:** Consume renderer `probe_duration` from Task 3 and nullable `ActiveEditorOut.render_duration` from Task 5. Store derived `render_duration` only with the current accepted `render_revision`; absent legacy metadata yields null rather than a fabricated calculated duration.

- [ ] **1. Write scheduler tests:** stale package plus no due occurrence enqueues no Reel; due occurrence enqueues/reuses one; ready current output creates/reuses review; invalid/failed input creates no approval-ready review. Assert:
  ```python
  assert [job for job in jobs_without_due if job.kind == "render"] == []
  assert len([job for job in jobs_with_due if job.kind == "render"]) == 1
  assert editor["render_duration"] == probed_file_duration
  ```
  Test later content edit fences an in-flight Reel; section-preview completion alone does not stale it. Missing duration metadata must not display montage duration as actual output duration.
- [ ] **2. Run red:** `uv run --project dojo-core pytest dojo-core/tests/test_review.py dojo-core/tests/test_empty_occurrence.py dojo-core/tests/test_render_revision_fence.py -v`.
- [ ] **3. Implement:** return before enqueueing if `_select_due_occurrence()` returns none. With a due occurrence, verify ready artifact existence, not only matching digest; otherwise enqueue/reuse render using existing failure guards. Probe actual file duration before attachment; store it with the accepted revision only. Explicit rendering remains unchanged and available with local drafts. Do not remove immutable review artifacts as active-preview cleanup.
- [ ] **4. Run green:** scheduler/render-fence tests and worker tick tests pass; existing manual/regular/oneoff review/publication tests retain explicit approval requirements.
- [ ] **5. Commit:** `fix: render automatic reels only when due`.

### Task 7: Web card-local commands and durable drafts

**Files:** Modify `web/src/packages/usePackageEditor.ts`, `drafts.ts` only if reconciliation needs a targeted change, `ActivePackagePanel.tsx` for minimal card-local call-site migration, `web/src/api/client.ts`; extend `usePackageEditor.test.tsx`, `drafts.test.ts`, `PackageEditorProvider.test.tsx`, `ActivePackagePanel.test.tsx`.

**Interfaces:** Change `save(id: string): Promise<boolean>`; retain `discard(id?: string): void` for internal replaced-package recovery but expose card-only calls in UI. Add `canSaveMedia(id: string): boolean`, `saveBlockedReasonFor(id: string): SaveBlockedReason`, and `retrySectionPreview(id: string): Promise<boolean>`. Extend removal to `remove(id: string, confirmedDiscard?: boolean): Promise<boolean>`; default false rejects a dirty target unless UI has confirmed. Add `api.retrySectionPreview(id: string, body: SectionPreviewRetryIn, signal?: AbortSignal): Promise<ActiveEditorOut>`.

- [ ] **1. Write hook tests:** changed A valid while B has blank/non-finite/over-limit input; exact one-group payload; B survives save/discard/reload; dirty photo saves independently; save response lost causes reconciliation, not write replay; failed removal retains A and B; confirmed successful removal deletes only A. Assert:
  ```typescript
  expect(sent.changes.map(group => group.key)).toEqual([`video:${a}`]);
  expect(result.current.draftInputs[b]).toEqual(beforeB);
  expect(result.current.canSaveMedia(a)).toBe(true);
  ```
  Test render/retry uses saved server inputs without submitting drafts, current Reel remains under dirty input, and stale retry refreshes instead of silently rendering another generation.
- [ ] **2. Run red:** `npm test -- src/packages/usePackageEditor.test.tsx src/packages/drafts.test.ts`.
- [ ] **3. Implement:** derive candidate values from persisted snapshot plus target card only; retain global command serialization and live/persistence gates. Send only the chosen stored group, use existing uncertainty persistence/reconciliation, and remove acknowledged groups only. Remove target draft after removal acknowledgment; do not optimistically discard before network success. Update all hook/type consumers and tests to the new required `id`; replace global controls with minimal per-card buttons now so typechecking and tests remain green before Task 8's layout work. Do not retain a global-save UI fallback.
- [ ] **4. Run green:** hook/provider/draft tests and `npm run typecheck` pass; no separate polling timer is introduced.
- [ ] **5. Commit:** `feat: save web media cards independently`.

### Task 8: Web cards, timeline, fullscreen viewer, and Reel panel

**Files:** Modify `web/src/packages/ActivePackagePanel.tsx`, `VideoSectionEditor.tsx`, `RangeTimeline.tsx`, `MediaActionIcon.tsx`, `web/src/components/PackageSummary.tsx`, `web/src/reviews/ReviewFlow.tsx`, `web/src/styles.css`, `web/src/i18n/tr.ts`; create `web/src/packages/SavedReelPanel.tsx`, `MediaFullscreenDialog.tsx` and corresponding `.test.tsx`; extend `ActivePackagePanel.test.tsx`, `VideoSectionEditor.test.tsx`, `RangeTimeline.test.tsx`, `PackageManager.test.tsx`, `web/e2e/package-management.spec.ts`.

**Interfaces:** `SavedReelPanel(): JSX.Element` consumes existing editor context. `MediaFullscreenDialog({media, onClose}: {media: EditorMediaOut; onClose(): void}): JSX.Element` uses original URL for videos and display image URL for photos. Extend `VideoSectionEditor` with persisted preview status and retry callback; source playback uses `original_url`, timeline bound remains `source_duration`.

- [ ] **1. Write UI/browser tests:** card-local controls/disabled reasons, photo label, one-line title, fixed collapsed heights, full-row expansion, image-only list network requests, original fullscreen URL and focus/Escape, error without fallback, source-above-section ordering, old preview retained until saved, empty saved selection hides it. Assert:
  ```typescript
  expect(video).toHaveAttribute("src", media.original_url);
  expect(screen.queryByText("Kaydedilecek değişiklik yok.")).not.toBeInTheDocument();
  expect(lastRange.end).toBe(sourceDuration);
  ```
  Cover source durations `6.123456` and `6.1238`: rounding cannot exceed duration. Browser tests verify touch/mouse and keyboard `End`, hit targets, no clipped final handle, Reel panel after upload controls, and rendered duration distinct from draft total.
- [ ] **2. Run red:** targeted component tests via `npm test -- src/packages` and `npm run test:browser -- e2e/package-management.spec.ts`.
- [ ] **3. Implement:** reuse `CollapsiblePanel`, existing icon/CSS patterns, and native modal dialog with initial focus, close, and focus restoration. Media list comes first after critical notices. A saved preview remains bound to persisted generation while editing; show warning for dirty input, states/retry for worker output, and no stale old video after save acknowledgment. Mount `SavedReelPanel` after `PendingActions` in `PackageSummary` and after the editor in `ReviewFlow`'s normal-package fallback, not inside `ActivePackagePanel`; assert exactly one Reel panel per applicable view. For a legacy ready artifact without stored duration, use loaded video metadata, never draft totals. Clamp after rounding and preserve exact terminal bound in timeline; preserve numeric inputs and section minimum length.
- [ ] **4. Run green:** components, browser package tests, `npm run build` pass. Inspect narrow/wide layouts with actual DOM size assertions; screenshots alone do not prove layout semantics.
- [ ] **5. Commit:** `feat: refine web active media panel`.

### Task 9: Android card-local draft and command parity

**Files:** Modify `android/app/src/main/java/com/dojo/aisomedo/editor/MediaEditorState.kt`, `editor/DraftStore.kt`, `AppViewModel.kt`, `api/DojoApi.kt`, and minimally migrate callbacks in `ui/MediaEditorPanel.kt` and `ui/DojoApp.kt`; extend `android/app/src/test/java/com/dojo/aisomedo/editor/MediaEditorTest.kt`, `DraftStoreTest.kt`, `AppViewModelTest.kt`, `OfflineAppViewModelTest.kt` and affected `android/app/src/androidTest/java/com/dojo/aisomedo/ui/MediaEditorPanelTest.kt` call sites.

**Interfaces:** Add state `isDirty(id: String): Boolean`, `canSave(id: String): Boolean`, `discard(id: String): MediaEditorState`, and `editPhotoDuration(id: String, value: String): MediaEditorState`; photo inputs use `RangeInput("0", value)` and `photo:<id>` groups. ViewModel exposes `saveMedia(id: String)`, `discardMedia(id: String)`, `editPhotoDuration(id: String, value: String)`, `retrySectionPreview(id: String)`, `renderActivePackage()`, `clearActivePackage(confirmed: Boolean)`, and `removeMedia(id: String, confirmedDiscard: Boolean = false)`. Preserve explicit package-rollover cleanup separately. `DojoApi.retrySectionPreview(id: String, body: SectionPreviewRetryIn): ActiveEditorOut` matches Task 5; `clearPackage(body: ClearPackageIn, expected: PackageRevision): ClearPackageOut` uses the existing server clear route.

- [ ] **1. Write model/ViewModel tests:** photo groups persist and rehydrate with correct baselines; saving A ignores B's invalid draft; discard affects only one ID; command sends exactly one group; independent server updates keep B; uncertain save is not replayed; network/session loss preserves drafts and gates mutations. Assert:
  ```kotlin
  assertEquals(listOf("photo:$photoId"), request.changes.map { it.key })
  assertEquals(beforeB, after.inputs[b])
  assertFalse(after.canSave(b))
  ```
  Failed confirmed removal preserves all drafts; successful removal discards only target. An unchanged target is not saveable. Render/retry never sends draft values, and stale preview requests cannot target another package. Android currently lacks package clearing: test explicit confirmation, exact captured package ID/revision, cleanup failure, lost response, and refresh-before-retry preventing a replacement package from being cleared.
- [ ] **2. Run red:** `.\gradlew.bat :app:testDebugUnitTest --tests "com.dojo.aisomedo.editor.*" --tests "com.dojo.aisomedo.AppViewModelTest"`.
- [ ] **3. Implement:** extend existing `StoredDraft` group encoding rather than inventing another store; use snapshot plus one group's proposal for candidate duration. Include photo values in `accept`, baseline extraction, conflict resolution, and persistence. Replace global trim-save callbacks with card IDs in production and test callers; add minimal card-local controls/photo field so this task compiles before Task 10's presentation work. Retain existing command uncertainty, generation/network fences, and live refresh. Reuse `DojoApi.renderPackage` for saved-Reel rendering. Implement confirmed clearing against a captured package ID/revision; mark uncertain outcomes read-required, preserve drafts until success is verified, and never blindly retry against a newly active package. Fetch preview files through the existing authenticated downloader, never an unauthenticated URL player.
- [ ] **4. Run green:** editor, persistence, ViewModel, and offline unit tests pass; `.\gradlew.bat :app:assembleDebug` compiles all updated callers.
- [ ] **5. Commit:** `feat: save android media cards independently`.

### Task 10: Android presentation and endpoint selection

**Files:** Modify `android/app/src/main/java/com/dojo/aisomedo/ui/MediaEditorPanel.kt`, `ui/DojoApp.kt`, `android/app/src/main/res/values/strings.xml`; create `ui/MediaRangeTimeline.kt`, `ui/MediaFullscreenDialog.kt`, `ui/SavedReelPanel.kt`; extend `android/app/src/androidTest/java/com/dojo/aisomedo/ui/MediaEditorPanelTest.kt`, `DojoAppTest.kt`; create `MediaRangeTimelineTest.kt` and `MediaFullscreenDialogTest.kt` alongside them.

**Interfaces:** `MediaRangeTimeline(duration: Double, ranges: List<VideoRangeOut>, disabled: Boolean, onChange: (List<VideoRangeOut>) -> Unit)`; `MediaFullscreenDialog(media: EditorMediaOut, onDismiss: () -> Unit, load: suspend (String, File) -> Unit)`; `SavedReelPanel(editor: MediaEditorState, enabled: Boolean, onRender: () -> Unit, load: suspend (String, File) -> Unit)`. `MediaEditorPanel` receives card-ID save/discard/photo/retry and confirmed clear callbacks from Task 9 and retains only one expanded video.

- [ ] **1. Write instrumented tests:** photo/video closed cards have equal height; expanded editor spans available width; card save/discard uses correct ID; photo duration editable; thumbnails do not request full videos; source and section preview remain separate; original format errors do not fallback; back closes viewer without discarding; reopen preserves draft. Assert:
  ```kotlin
  assertEquals(sourceDuration, capturedRanges.last().end, 0.0)
  assertEquals(originalUrl, requestedPreviewUrl)
  assertEquals(beforeB, editorAfterSave.inputs[b])
  ```
  Use numeric bounds with normalized/original duration mismatch and non-millisecond duration. Test touch drags to both ends, semantics actions/numeric alternatives, loading/failure/retry, dirty warning, and saved-Reel placement after uploads/pending controls.
- [ ] **2. Run red:** `.\gradlew.bat :app:connectedDebugAndroidTest`; new UI assertions fail on an available emulator/device. If unavailable, compile instrumentation and report execution blocked.
- [ ] **3. Implement:** use existing Compose/dialog/player and `RemoteMediaPreview` download patterns, making image-only thumbnail display explicit. `MediaThumbnail.kt` currently extracts local frames and is not justification to download each remote video; reuse its image sizing patterns only. Keep full filename in semantics/tooltip, icons labeled, fixed collapsed cards and full-row content-height expanded cards, and required Turkish copy. Original viewer/player must accept declared MIME/type rather than silently forcing all originals to processed MP4. Preserve temporary-file cleanup and session bounds. Add accessible touch timeline and numeric inputs, clamping after rounding. Place separate Reel composable last in the package page; show actual `renderDuration`, falling back to loaded file metadata for a legacy ready artifact rather than calculated montage total.
- [ ] **4. Run green:** `.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest`, then `:app:connectedDebugAndroidTest` on device. Exercise narrow and wide layouts; no new dependencies or background polling service.
- [ ] **5. Commit:** `feat: refine android active media panel`.

### Task 11: End-to-end acceptance and regression gate

**Files:** Extend `backend/tests/test_live_integration.py`, `web/e2e/package-management.spec.ts`, `worker/tests/test_worker_tick.py` only for uncovered end-to-end cases; update `docs/active_package_media_panel.md` workflow status. No standalone duplicate harness.

**Interfaces:** Consume all preceding task interfaces; no new production contract.

- [ ] **1. Add any missing failing integration check:** save A while B is invalid; observe worker queued→ready through SSE refresh; confirm content revision unchanged on completion, B retained, original still accessible, section output correct, and no automatic Reel without a due occurrence. Advance fake schedule to due, verify exactly one current Reel and ready review, then assert no publication before approval. Assert no preview control-check timer appears as a client data polling loop.
- [ ] **2. Run the integration check red if it exposes a gap:** `uv run --project backend pytest backend/tests/test_live_integration.py -v`; fix only the owning task's boundary, not an endpoint-local workaround. If preceding work already satisfies the check, record that it was an acceptance test, not a new TDD failure claim.
- [ ] **3. Run Python CI-equivalent verification:** separately run `uv run --project dojo-core pytest dojo-core/tests -v`, `uv run --project backend pytest backend/tests -v`, `uv run --project worker pytest worker/tests -v`; run Ruff and mypy for each project's `src` using `.github/workflows/ci.yml` commands. Require real PostgreSQL and real media checks, not only in-memory/mocked suites.
- [ ] **4. Run clients and contracts:** from `web`, `npm test`, `npm run build`, `npm run test:browser`; Android commands from Task 10; regenerate schema/clients again and require `git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt` after committed generation. Run `git diff --check`.
- [ ] **5. Review and commit:** inspect whole-branch diff against the spec and the five Review Focus cases; execute the selected independent review workflow, address findings, and rerun affected checks. Commit acceptance changes as `test: verify active media panel workflows`. Mark workflow implementation complete only when evidence exists; explicitly list any blocked environment checks and do not claim full completion while required checks remain blocked.

## Coverage and handoff

Spec sections 4–6 map to Tasks 1–5 and 7/9; section 7 maps to Tasks 3–5 and 8/10; section 8 maps to Tasks 7–10; section 9 maps to Tasks 6, 8, and 10; all acceptance criteria in section 10 map to Task 11 plus their owning red/green tasks. The plan's 0.25-second cancellation interval, 2-second termination grace, 900-second preview deadline, 5-second recovery grace, and 640-pixel thumbnail bound are implementation defaults selected here, not previously agreed product promises; review them with this plan.

Plan self-review checks: spec coverage, action granularity, cross-task type/signature consistency, five Review Focus tests, and scope/proportion. Written plan approved by the user; Native execution selected on branch `feature/active-package`.
