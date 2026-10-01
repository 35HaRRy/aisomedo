# Web Resumable Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement #27: Turkish browser media uploads with progress, pause/retry, metadata-only reload recovery, and authoritative size/validation feedback.

**Architecture:** Keep existing backend upload/worker semantics; add a read-only limits endpoint and generated browser DTOs. A React-independent controller owns a sequential transfer queue and client-scoped metadata; a paired-shell provider preserves selected files across navigation and renders controls in Current Package.

**Tech Stack:** Existing Python 3.12, FastAPI/Pydantic, React 18, TypeScript/Vite, Web Crypto, localStorage, pytest, Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-01-web-resumable-upload-design.md` (user approved).

## Global Constraints

- Sequential, checksummed 2 MiB chunks; backend ceiling remains 8 MiB.
- No entire-file arrayBuffer, persisted File/Blob contents, new product dependencies, or database migrations.
- Backend limits load before initiation; local oversize/zero-byte rejection and backend capacity rejection send zero chunks.
- `received_ranges` are half-open `[start, end)` pairs; confirmed progress comes from backend `received_bytes`.
- Reload requires original-file reselection and content-fingerprint verification before any resume PUT.
- Only `finalized` is success; queued/processing is not validated package media.
- All authored copy and accessibility labels live in the Turkish string catalog.
- Reuse existing pairing, same-origin cookie transport, session generations, and five-second foreground refresh.
- HTTP 401 clears protected UI/File references and invalidates session; network errors do not.
- FastAPI generates committed OpenAPI/TypeScript/Kotlin artifacts; no Android minimum-version bump.
- Filename conflicts stop transfer; resolution stays #28. No background uploads, cross-tab locks, or new initialization-idempotency protocol.

## Review Focus

- Lost initialization response must not send bytes using an unknown ID; retry is explicit and may leave an empty server record (Task 4).
- Same-size/same-name different content and changed chunk boundaries must not attach to a saved upload (Tasks 2, 4).
- Corrupt metadata, quota errors, and blocked localStorage access must not crash or falsely promise reload recovery (Tasks 2, 4, 5).
- Pausing or losing authentication while digest/PUT completes must reject late work and preserve other eligible queue rows (Tasks 3–5).
- A completion conflict, stale terminal status, or malformed server ranges must not loop, recreate an upload, or display invalid progress (Tasks 3–5).

## File responsibilities

- `backend/src/backend/routes/media.py`: authenticated limits DTO/router beside existing upload routes.
- `backend/scripts/generate_clients.py`: add upload DTO schema roots; generated artifacts remain generated.
- `web/src/api/client.ts`: typed upload transport and additive safe textual HTTP detail.
- New `web/src/uploads/types.ts`: public controller/transport/row/persistence types and `CHUNK_BYTES`.
- New `web/src/uploads/identity.ts`: cancellable bounded-memory chunk hashes and fingerprint.
- New `web/src/uploads/storage.ts`: versioned, validated client-scoped metadata only.
- New `web/src/uploads/transfer.ts`: range reconciliation and one-file chunk/completion protocol.
- New `web/src/uploads/controller.ts`: queue, actions, persistence, status refresh, lifetime guards.
- New `web/src/uploads/UploadProvider.tsx`: session-bound React adapter and foreground polling.
- New `web/src/uploads/UploadPanel.tsx`: localized accessible file picker/rows/actions.
- `web/src/App.tsx`, `components/PackageSummary.tsx`, `i18n/tr.ts`, `styles.css`: shell and package integration.
- Tests beside modules and `backend/tests/test_upload_limits_api.py`; `docs/verification/issue-27-web-upload.md` records real verification evidence.

## Task 1: Authenticated limits and typed upload transport

**Files:** Modify `backend/src/backend/routes/media.py`, `backend/src/backend/main.py`, `backend/scripts/generate_clients.py`, `backend/tests/test_client_generation.py`, `web/src/api/client.ts`, `web/src/api/client.test.ts`. Create `backend/tests/test_upload_limits_api.py`. Regenerate `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`.

**Interfaces:**
- `UploadLimitsOut(BaseModel)` with integer `max_file_bytes`, `max_package_bytes`; authenticated `GET /api/media/upload-limits` calls existing `get_upload_limits()` without mutation. Use a sibling `/api/media` router included alongside the current router; keep all upload URLs intact.
- Generate `UploadLimitsOut`, `UploadInitIn`, `UploadOut` via `typescript_models` roots.
- Preserve `ApiError(status: number)` callers; extend constructor with optional `detail?: string`.
- Add `api.uploadLimits(signal?) -> Promise<UploadLimitsOut>`, `api.startUpload(body: UploadInitIn, signal?) -> Promise<UploadOut>`, `api.uploadStatus(id: string, signal?) -> Promise<UploadOut>`, `api.uploadRange(id: string, offset: number, checksum: string, body: Blob, signal?) -> Promise<UploadOut>`, `api.completeUpload(id: string, signal?) -> Promise<UploadOut>`.

- [ ] **1. Write backend tests:** `test_limits_requires_pairing` asserts 401 before pairing and after revocation. `test_limits_defaults_and_read_only` asserts 2 GiB/20 GiB defaults, no active package, no new uploads/jobs, and unchanged audit count after GET. `test_limits_configured_values` sets 5/100 bytes through existing test settings fixture and asserts exact response.
- [ ] **2. Run red:** `uv run --project backend pytest backend/tests/test_upload_limits_api.py -v`; expect missing-route failures.
- [ ] **3. Implement limits DTO/route:** inject existing publishing facade and pairing dependency. Register sibling limits router in `backend/src/backend/main.py` if needed; do not change `/api/media/uploads` prefix or processing behavior.
- [ ] **4. Add failing generator and client tests:** generated output includes all three DTOs; wrappers send correct relative paths, encoded ID/query values, POST JSON/init, PUT Blob/range, POST/complete, and same-origin credentials. JSON `{detail: "chunk checksum mismatch"}` preserves textual detail/status; plain text, invalid JSON, and structured validation-detail arrays preserve status but do not expose raw body/input.
- [ ] **5. Implement schema roots and wrappers:** range content type `application/octet-stream`; preserve ten-second request timeout and caller AbortError behavior. Parse only a textual JSON `detail` on HTTP error, with parse-failure fallback to status-only `ApiError`. Regenerate using `uv run --project backend python backend/scripts/export_openapi.py` then `uv run --project backend python backend/scripts/generate_clients.py`.
- [ ] **6. Run green:** backend limits/client-generation/contract tests; `npm --prefix web test -- src/api/client.test.ts`; `npm --prefix web run typecheck`. Expect PASS and no regressions in existing transport callers.
- [ ] **7. Commit scoped files:** `feat(api): expose upload limits and typed transport`.

## Task 2: Content identity and metadata persistence

**Files:** Create `web/src/uploads/{types,identity,storage}.ts`, `identity.test.ts`, `storage.test.ts`.

**Interfaces:**
- `CHUNK_BYTES = 2 * 1024 * 1024`.
- `FileIdentity = { chunkBytes: number; chunkHashes: string[]; fingerprint: string }`.
- `fingerprintFile(file: File, signal: AbortSignal, onProgress?: (bytes: number) => void): Promise<FileIdentity>`; lowercase 64-character SHA-256 hashes.
- `UploadPhase = "preparing" | "waiting" | "uploading" | "paused" | "needs-file" | "retryable" | "queued" | "processing" | "finalized" | "failed" | "conflict" | "expired"`.
- `UploadRow`: `id`, `filename`, `size`, `contentType`, `lastModified`, `phase`, `preparedBytes`, `status: UploadOut | null`, `identity: FileIdentity | null`, `error: UploadErrorCode | null`, `diagnostic: string | null`. File itself is never in public/persisted rows.
- `UploadErrorCode = "network" | "server" | "empty" | "oversize" | "capacity" | "checksum" | "wrong-file" | "hash-unavailable" | "expired" | "conflict" | "invalid-response"`.
- Export `UploadFlowError extends Error` with constructor `(code: UploadErrorCode, diagnostic?: string)` and readonly code/diagnostic fields. Identity/transfer use it for local failures; controller maps it to rows without exposing arbitrary exception text.
- `SavedUpload`: row ID, filename/size/type/time, identity, nullable upload status. Storage envelope `{version: 1, records: SavedUpload[]}`. Key `aisomedo.uploads.v1:${clientId}`.
- `readUploads(storage: Pick<Storage, "getItem">, clientId: number): {records: SavedUpload[]; available: boolean}`; `writeUploads(storage: Pick<Storage, "setItem">, clientId: number, records: SavedUpload[]): boolean`.

- [ ] **1. Write identity tests:** `hashes_only_bounded_slices` creates `CHUNK_BYTES + 3` bytes, expects two hashes, reads at most `CHUNK_BYTES`, and forbids whole-file reads. `same_content_matches` ignores changed modification time; `same_name_size_changed_content_differs` changes one byte and expects different fingerprint. `cancel_during_digest` aborts before delayed digest settles and asserts AbortError/no further reads. `missing_crypto_is_actionable` rejects without starting a transfer.
- [ ] **2. Run red:** `npm --prefix web test -- src/uploads/identity.test.ts`; expect missing-module failures.
- [ ] **3. Implement identity/types:** use FileReader on slices for cancellable reads and `crypto.subtle.digest("SHA-256", bytes)`; check abort before/after asynchronous work. Fingerprint SHA-256 of UTF-8 `JSON.stringify({chunkBytes: CHUNK_BYTES, size: file.size, chunkHashes})` with this exact property order. Never hash an entire video buffer. Use scoped Node Web Crypto stub in tests if jsdom lacks subtle crypto; do not add dependencies or alter global test setup indiscriminately.
- [ ] **4. Write storage tests:** roundtrip retains metadata but no File/Blob or credentials; different client IDs are isolated. Bad JSON/version/types, unsafe sizes, wrong chunk size/count, invalid hashes, invalid status/ranges, and duplicate row/upload IDs are ignored safely. Throwing getItem returns unavailable; throwing setItem returns false. Last-modified must be finite; progress must be within declared size.
- [ ] **5. Implement storage:** validate unknown parsed values, permit only known phases/statuses/primitive metadata, and serialize an explicit allowlist rather than spreading controller objects. Persist only completed identities; unfinished preparation is transient. A saved row without upload ID restores as needs-file for explicit new initiation, not as an already existing server upload.
- [ ] **6. Run green:** `npm --prefix web test -- src/uploads/identity.test.ts src/uploads/storage.test.ts`; `npm --prefix web run typecheck`. Expect PASS.
- [ ] **7. Commit:** `feat(web): persist verified upload metadata`.

## Task 3: Reconciled single-file transfer

**Files:** Create `web/src/uploads/transfer.ts`, `transfer.test.ts`; extend `types.ts`.

**Interfaces:**
- `UploadTransport`: `limits(signal): Promise<UploadLimitsOut>`, `start(body: UploadInitIn, signal): Promise<UploadOut>`, `status(id: string, signal): Promise<UploadOut>`, `range(id: string, offset: number, checksum: string, body: Blob, signal): Promise<UploadOut>`, `complete(id: string, signal): Promise<UploadOut>`; all signals are `AbortSignal`.
- `transferUpload(file: File, identity: FileIdentity, initial: UploadOut, transport: UploadTransport, signal: AbortSignal, onStatus: (status: UploadOut) => void): Promise<UploadOut>`.
- Validate every response against known upload ID/file size, integer bounded sorted nonoverlapping ranges, received-byte sum, and known statuses (`receiving`, `conflict`, `queued`, `processing`, `finalized`, `failed`, `aborted`) before publishing progress. Invalid responses throw `UploadFlowError("invalid-response")`, not an infinite scheduling loop. Server `aborted` maps to local expired; cleanup uses aborted, not a separate wire expired status.

- [ ] **1. Write failing reconciliation test:**
  ```typescript
  it("skips confirmed chunks and retransmits partial chunks", async () => {
    // Three chunks; GET acknowledges first and half of second.
    const { file, identity, initial, transport, changed } = fixture(3 * CHUNK_BYTES);
    transport.status.mockResolvedValue(status([[0, CHUNK_BYTES + 10]], file.size));
    await transferUpload(file, identity, initial, transport, new AbortController().signal, changed);
    expect(transport.range.mock.calls.map(call => call[1])).toEqual([CHUNK_BYTES, 2 * CHUNK_BYTES]);
    expect(transport.complete).toHaveBeenCalledTimes(1);
  });
  ```
  Define `fixture` and `status` locally in this test file; status updates must report growing server coverage, not a permanently incomplete response.
- [ ] **2. Run red:** `npm --prefix web test -- src/uploads/transfer.test.ts`; expect missing transfer implementation.
- [ ] **3. Implement reconciliation:** GET known ID before transfer; skip only fully covered slices. PUT raw slice and its stored hash; final slice may be short. Report server-confirmed status after each acknowledgement and honor non-receiving states immediately. If a PUT or complete fails ambiguously, reconcile GET; accepted queued/processing/finalized complete is success, receiving returns a retryable error rather than looping. A later explicit retry may complete the known upload.
- [ ] **4. Add failure tests:** lost PUT response then explicit retry uses same ID and skips stored bytes; lost complete response with queued status never calls start/complete again. Complete 409 with finalized status succeeds; 409 still receiving fails without loop. Pause while PUT completes causes no callback/next PUT. 404, malformed/out-of-bounds ranges, wrong ID/size, unknown status, and nonadvancing acknowledgement stop safely. Conflict/failed/aborted status sends no more bytes. Assert one request at a time and no double-counted progress.
- [ ] **5. Run green:** `npm --prefix web test -- src/uploads/transfer.test.ts`; `npm --prefix web run typecheck`. Expect PASS.
- [ ] **6. Commit:** `feat(web): reconcile resumable chunk transfers`.

## Task 4: Queue controller and reload recovery

**Files:** Create `web/src/uploads/controller.ts`, `controller.test.ts`; extend `types.ts`.

**Interfaces:**
- `UploadSnapshot = {rows: readonly UploadRow[]; limits: UploadLimitsOut | null; limitsError: boolean; storageAvailable: boolean}`.
- `createUploadController({clientId, transport, storage, onUnauthorized, onPackageChanged}): UploadController`; callbacks return void, client ID is number, storage is `Storage | null`.
- `UploadController`: `getSnapshot(): UploadSnapshot`, `subscribe(listener: () => void): () => void`, `initialize(signal: AbortSignal): Promise<void>`, `add(files: readonly File[]): Promise<void>`, `pause(id: string): void`, `resume(id: string, file?: File): Promise<void>`, `retry(id: string, file?: File): Promise<void>`, `dismiss(id: string): void`, `refresh(signal: AbortSignal): Promise<void>`, `dispose(): void`.
- Snapshot contains immutable row copies; internal map owns File references and operation generations. `initialize` restores metadata/reconciles saved IDs and loads limits. `refresh` polls only queued/processing IDs; known receiving rows require explicit resume. All request lanes for the same row are serialized.

- [ ] **1. Write controller tests:** `oversize_or_empty_has_no_start_or_hash` rejects size > configured limit or zero bytes. `limits_failure_blocks_add_and_can_reload` shows error and allows initialize retry. `capacity_or_413_sends_no_ranges` maps backend rejection. `files_transfer_sequentially` defers first PUT and asserts second file cannot transfer yet; pausing/failed first row permits second. Assert completed transfer enters queued, not finalized.
- [ ] **2. Run red:** `npm --prefix web test -- src/uploads/controller.test.ts`; expect missing controller failures.
- [ ] **3. Implement queue lifecycle:** load configured limits, fingerprint before initialization, persist identity and known ID before first chunk, and persist confirmed changes. Use Task 3 transport. New uploads refresh limits before explicit new attempts. Queue operations are cancellable; duplicate clicks cannot schedule duplicate work. Initialization response loss produces retryable row with no guessed ID/PUT; explicit retry alone may initialize a new record. Map textual capacity/checksum detail only for known HTTP statuses; unexpected errors remain generic.
- [ ] **4. Add recovery tests:** reconstruct controller from shared storage; same-content reselection resumes same ID after fresh GET; same-name/size modified file sends zero PUTs. Changed modification time with unchanged content is accepted. Receiving rows restore needs-file; queued/processing rows restore and poll without a file. 404/aborted permits only explicit fresh-upload retry; conflict blocks transfer and no resolve call exists. Validation failure retains diagnostic and requires an explicit new attempt; terminal dismiss removes metadata. A saved no-ID record initiates only after explicit reselection. Blocked storage getter/write leaves in-memory upload functional and marks recovery unavailable.
- [ ] **5. Add lifetime tests:** `dispose_during_preparation_or_put_ignores_late_results` checks no callbacks/writes/new requests after disposal. 401 on limits/status/start/range/complete calls onUnauthorized, aborts all work, and clears files/snapshot; non-401 errors preserve rows. Restore/query response with wrong file size or ID becomes invalid-response. Repeated refresh/resume calls never race requests for the same ID. Initialization and finalized transition call onPackageChanged once per accepted transition; stale terminal responses cannot regress finalized to receiving.
- [ ] **6. Run green:** all uploads module tests and web typecheck. Expect PASS; verify no controller exports or snapshot/persistence contain File references.
- [ ] **7. Commit:** `feat(web): recover upload queues after reload`.

## Task 5: Session-bound provider and accessible package UI

**Files:** Create `web/src/uploads/UploadProvider.tsx`, `UploadPanel.tsx`, `UploadPanel.test.tsx`, `UploadProvider.test.tsx`. Modify `web/src/App.tsx`, `components/PackageSummary.tsx`, `i18n/tr.ts`, `styles.css`, `App.test.tsx` and shared fixtures only where required.

**Interfaces:**
- `UploadProvider({children, onPackageChanged}: {children: ReactNode; onPackageChanged: () => void})`; obtains paired client and invalidate from existing session. Expose `useUploads(): {snapshot: UploadSnapshot; controller: UploadController}` through context.
- `UploadPanel(): JSX.Element`; package child consumes provider, no transport logic in panel.
- Wrap paired-shell content with provider after creating dashboard live-data hook; pass stable `snapshot.retry` callback (stabilize it with useCallback in `web/src/useLiveData.ts` if necessary). Keep provider outside conditional area rendering so navigation preserves files. Under StrictMode, effect setup creates a fresh live controller and cleanup disposes that instance; never reuse disposed controller.

- [ ] **1. Write UI tests:** picker disabled until limits load; selection shows filename/native progress and localized phase; pause/resume/retry act on intended row. Reload needs-file row offers labelled reselection; wrong file error remains adjacent to row. Queued/processing is not success; failed diagnostic `<script>bad</script>` appears as text and creates no script element. Conflict has no overwrite action. Storage warning explicitly says reload recovery unavailable. Terminal dismiss removes row. All labels/status strings come from catalog.
- [ ] **2. Run red:** `npm --prefix web test -- src/uploads/UploadPanel.test.tsx src/uploads/UploadProvider.test.tsx`; expect missing components.
- [ ] **3. Implement provider:** subscribe to snapshot, initialize under paired-session lifetime, and run controller.refresh through existing startLiveRefresh. Dispose/unsubscribe on unmount/session change; 401 uses invalidate. Guard initialization/status callbacks against obsolete controller. Handle localStorage getter failure before constructing controller. No polling overlap or teardown leaks.
- [ ] **4. Implement panel and integration:** multiple-file input with format hints; per-row actions only in valid phases. Use native progress labelled by filename, polite phase announcements, localized errors and byte-size/percentage formatting. Preparing displays preparation separately from confirmed transfer progress. Reset picker after selection so identical files can be chosen again. Retry failed/expired rows without retained file requires reselection before a new upload. Wrap long filenames; preserve 320px layout and focus visibility. Refresh package via provider callback; update existing App fixtures with limits response rather than masking unexpected fetches.
- [ ] **5. Add provider/shell tests:** navigation away/back preserves current File/row and does not duplicate transfers. Hidden page cancels status polling; focus/online wakes once; five-second ticks do not overlap. Session revocation during digest/PUT returns pairing and ignores late progress. StrictMode effect replay starts one live controller without disposed-controller reuse. Loss of storage must not crash render. Existing onboarding/session/dashboard tests still pass.
- [ ] **6. Run green:** `npm --prefix web test`; `npm --prefix web run typecheck`; `npm --prefix web run build`. Expect all tests/build PASS.
- [ ] **7. Commit:** `feat(web): add package upload progress and recovery UI`.

## Task 6: Integrated verification and acceptance evidence

**Files:** Create `docs/verification/issue-27-web-upload.md`; modify tests from Tasks 1–5 only if acceptance gaps appear. No speculative production refactors.

**Interfaces:** No new product interfaces. Evidence records exact commands, results, limitations, and desktop/mobile browser observations.

- [ ] **1. Write missing acceptance tests before any discovered fix:** integrated upload, pause after server stores chunk but before response, explicit retry, reload/reselection, wrong-file rejection, worker failed/finalized outcomes, and 401. Tests drive actual upload API wrappers through deterministic fetch fixtures, not only a prepopulated UI snapshot. Run failing case to establish regression before patching.
- [ ] **2. Run verification from repository root:**
  ```text
  npm --prefix web test
  npm --prefix web run typecheck
  npm --prefix web run build
  uv run --project backend pytest backend/tests -v
  uv run --project backend ruff check backend/src backend/tests
  uv run --project backend mypy backend/src/backend
  uv run --project backend python backend/scripts/export_openapi.py
  uv run --project backend python backend/scripts/generate_clients.py
  git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt
  git diff --check
  ```
  Expect PASS/exit 0. Contract drift check runs after Task 1 artifacts are committed. Record environmental blockers or unrelated preexisting failures accurately; do not call them passing.
- [ ] **3. Browser acceptance:** serve Vite with deterministic intercepted API responses and small local File fixtures. Check desktop 1440px and mobile 320px, keyboard picker/actions, long filenames/no horizontal overflow, pause/progress/error states, reload/reselection, and queued-to-finalized/failed transitions. Ensure interception captures all chunk bytes so no fixture calls reach production. Stop temporary dev server when verification ends.
- [ ] **4. Record evidence:** link tests to #27's three acceptance criteria, include actual test totals/commands and browser results; explicitly state if live multi-gigabyte, real worker, or browser checks were not run. Known init-response-loss limitation and metadata-only recovery remain documented.
- [ ] **5. Perform final diff review:** no persisted content/tokens, no hidden success-before-finalization, no conflict-resolution scope creep, bounded-memory hashing, correct chunk/query protocol, generated-artifact freshness, clean task commits. Request whole-branch review using chosen execution workflow before reporting implementation complete; do not close issue or publish PR without user instruction.
- [ ] **6. Commit evidence/scoped corrections:** `docs(web): record resumable upload verification`.

## Plan self-review

Spec coverage: Tasks 1–2 cover limits, contract, file identity, and persistence;
Tasks 3–4 cover queue/reconciliation/recovery/session errors; Task 5 covers UI,
navigation, Turkish copy, polling, and accessibility; Task 6 records acceptance.
All five Review Focus conditions have explicit owning tests above. Transport,
identity, storage, and controller signatures are consistent across tasks.
Plan does not authorize implementation until user reviews it and selects execution.
