# Web Media Management and Multi-Range Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #29 with reversible media management, persisted ordering, a visual multi-range video editor, accurate duration feedback, and private completed-package browsing/downloads.

**Architecture:** Extend `DojoPublishing` with canonical retained selections and safe artifact reads. Thin typed FastAPI routes expose generated contracts; a session-scoped web editor keeps authoritative snapshots separate from local drafts. Expand each selected video into existing render segments rather than introducing a separate renderer or browser export pipeline.

**Tech Stack:** Existing Python 3.12, FastAPI/Pydantic, React 18, TypeScript/Vite, pytest, Vitest/Testing Library, Docker-backed FFmpeg; add Playwright Test as a development-only dependency for real-browser interaction tests.

**Spec:** `docs/superpowers/specs/2026-10-02-web-media-management-timeline-design.md` (written specification approved by user).

## Global Constraints

- Originals remain unchanged; Tamamlanmış Paket contents are immutable and browse/download-only.
- Ranges retain selected material in source-time order; `0 <= start < end <= source_duration`, finite endpoints, minimum `1/25` second, no duplicates/overlap; adjacent ranges allowed.
- Omitted video ID means full video; API empty arrays are invalid. The browser's empty range list removes the map key.
- Arrow keys adjust by `0.1` seconds; Shift+Arrow by `1` second. Add at playhead with initial length `1` second or the remaining usable gap.
- Whole montage duration includes configured photos, retained video sections, and enabled intro/outro cards once. No silent truncation/splitting; rejected saves write nothing.
- Legacy single-range data means retained range, matching actual renderer output. Preserve legacy digest shape until explicit canonical edits; block legacy replacement of multi-range selections.
- Preserve Turkish localization, incumbent white/gray/teal styling, visible focus, minimum `44px` actions, equal browser/device authorization, and existing uploads/onboarding/review behavior.
- Same-origin authenticated previews/downloads only; `/pub/{token}` remains approved-render-only. Never expose absolute filesystem paths or buffer entire downloads in browser memory.
- New editor mutations carry expected package identity; no new general cross-client revision protocol or database migration.
- Generate OpenAPI/TypeScript/Kotlin artifacts from backend source; no handwritten generated DTOs or Android UI changes.
- No new product runtime dependencies. Playwright is test-only. Do not install dependencies or change product code before plan approval and execution-method selection.

## Review Focus

- Turkish/Unicode filenames and upper-case or absent extensions must download safely without changing stored originals (Tasks 3–4).
- A gap shorter than one output frame, pointer cancellation, or dragging past a neighboring selection must never save a zero-length/overlapping section (Tasks 6, 8).
- Removing a selected video, then saving other videos and restoring it, must preserve its sections and saved position (Tasks 1, 3, 7).
- A lost save response or a package rollover while a request is in flight must not report false success or retry against a new active package (Tasks 4–5, 7).
- Unrelated five-second refreshes must not erase drafts, while changed media/sections must make those drafts visibly stale (Tasks 5, 7).

## File Structure and Ownership

| Scope | Files and responsibility |
| --- | --- |
| Domain selections | New `dojo-core/src/dojo/montage.py`: normalization, validation, duration; existing `model.py`, `publishing.py`, `exceptions.py`, `__init__.py`: public facade and exported DTOs/errors. |
| Rendering | Existing `dojo-core/src/dojo/adapters/render.py`: uniquely named retained segments; `publishing.py`: build/digest integration. |
| Private artifacts | New `dojo-core/src/dojo/package_media.py`: manifest-bound artifact discovery/resolution; `publishing.py`: active/completed read operations. |
| API/contracts | New `backend/src/backend/routes/package_models.py`: DTOs; existing `routes/packages.py`: transport/auth/error mapping; `backend/scripts/generate_clients.py`: DTO roots. |
| Web data/state | Existing `web/src/api/client.ts`: transport; new `web/src/packages/ranges.ts`, `usePackageEditor.ts`, `PackageEditorProvider.tsx`: pure range operations, live snapshots/drafts, session-scoped ownership and navigation guard. |
| Timeline | New `web/src/packages/RangeTimeline.tsx`, `VideoSectionEditor.tsx`: accessible graphical selection and native preview with exact controls. |
| Package surface | New `web/src/packages/ActivePackagePanel.tsx`, `CompletedPackages.tsx`, `PackageManager.tsx`; existing `components/PackageSummary.tsx`, `App.tsx`, `navigation.ts`, `i18n/tr.ts`, `styles.css`: composition, guard integration, strings, responsive styling. |
| Browser verification | New `web/playwright.config.ts`, `web/e2e/package-management.spec.ts`, `web/e2e/fixtures/timeline.mp4`; existing test config/package lock/CI; new `docs/verification/issue-29-web-media-management.md`. |

Test files live beside web units. New Python seam tests: `dojo-core/tests/test_selections.py`, `test_package_editor.py`, `test_render_selections.py`, and `backend/tests/test_package_editor_api.py`. Reuse existing test helper patterns, not cross-workspace imports of test modules.

## Execution Setup

- [ ] Use `using-git-worktrees` at execution time; preserve unrelated work and verify baseline status/tests. Record missing Docker/browser/FFmpeg prerequisites rather than treating skipped checks as success.
- [ ] Read the approved spec and this plan. Before library-specific implementation, fetch current React/FastAPI/Playwright documentation using Context7; no secrets or source code in queries. Before UI edits, load Impeccable's craft floor; preserve incumbent styling.
- [ ] At every task, write its behavioral tests, observe the intended failure, implement only that deliverable, rerun focused tests plus affected regressions, and commit only named task files. Update these checkboxes with actual results.

---

### Task 1: Canonical retained selections and coherent duration — complete

Verified: 25 expected RED failures; 57 focused tests passed; full core suite 617 passed/3 existing skips and backend 135 passed. Commit: `9c377b3`. Existing unrelated lint/typecheck findings are recorded in the execution ledger.

**Files:** Create `dojo-core/src/dojo/montage.py`, `dojo-core/tests/test_selections.py`; modify `dojo-core/src/dojo/model.py`, `exceptions.py`, `__init__.py`, `publishing.py` (montage methods around 1996–2160), and `dojo-core/tests/test_montage.py`.

**Interfaces:** Export `VideoRange` TypedDict (`start: float`, `end: float`), `VideoSelections = dict[str, list[VideoRange]]`, `REEL_FPS = 25`, `PackageChanged`, and `LegacyTrimConflict`. Add `DojoPublishing.set_selections(selections: VideoSelections, requester: str | None = None, *, expected_folder_name: str) -> MontageStatus`. Extend `set_order`, `set_trims`, `remove_media`, and `restore_media` with optional keyword-only `expected_folder_name: str | None = None`. Add defaulted `MontageStatus.selections`, `card_duration`, and `duration_complete` fields; incomplete source duration is visible and blocks mutations requiring a known total/rendering.

- [ ] **Write failing seam tests.** Build local `make_seam`/`finalize_media` helpers using the setup pattern in `test_montage.py`. The primary assertion is:

```python
def test_selected_sections_are_retained(tmp_path):
    store, seam = make_seam(tmp_path)
    video = finalize_media(tmp_path, seam, store, filename="clip.mp4", content_type="video/mp4", duration=30.0)
    ranges = [{"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 15.0}, {"start": 24.0, "end": 30.0}]
    status = seam.set_selections({video: ranges}, expected_folder_name=seam.get_active_package().folder_name)
    assert status.combined_duration == 16.0
    assert status.selections[video] == ranges
```

Add named cases for finite endpoints/booleans, `1/25` minimum, overlap/duplicates, adjacency, sorting, empty arrays, photos/unknown/removed targets, invalid source duration, no active package, expected-folder mismatch, completed IDs, batch correction, actor audit and stale revision. Pin floating-point boundary behavior: `[10, 10.04)` is a valid one-frame range; minimum-length comparison permits only `1e-9` seconds of arithmetic tolerance, not a shorter user-visible section. `test_removed_sections_survive_other_video_save` removes selected A, edits B, restores A, and asserts A's ranges/position survive. Test a 30-second legacy range 10–20 totals 10 seconds rather than the old 20; rewrite old duration/over-limit expectations accordingly. Test cards counted once and rejection leaves manifest bytes unchanged.
- [x] **Observe RED:** `uv run --project dojo-core pytest dojo-core/tests/test_selections.py -v` — missing facade operation/assertion failures, not broken imports.
- [ ] **Implement selection rules.** In `montage.py`, define `manifest_selections(manifest: dict) -> VideoSelections`, `validate_ranges(ranges: list[VideoRange], source_duration: float) -> list[VideoRange]`, and `effective_duration(entry: dict, ranges: list[VideoRange] | None, photo_seconds: float) -> float`. Use one interpretation for status and mutation checks, reject invalid numeric inputs before conversion, preserve removed selections, and synchronize legacy single-range projection. Card accounting uses the same copied branding/assets/default-duration rules as `_build_reel`. Guard legacy replacement when active multi-ranges exist; validation completes before any manifest/audit write.
- [x] **Observe GREEN/regressions:** `uv run --project dojo-core pytest dojo-core/tests/test_selections.py dojo-core/tests/test_montage.py dojo-core/tests/test_media_removal.py -v` — all pass.
- [x] **Commit named files:** `feat(core): retain multiple video sections`.

### Task 2: Render actual retained sections without duplicate outputs

**Files:** Modify `dojo-core/src/dojo/publishing.py` (`_render_digest`, `_build_reel`, render-limit check), `dojo-core/src/dojo/adapters/render.py`, `dojo-core/tests/test_render.py`; create `dojo-core/tests/test_render_selections.py` and `dojo-core/tests/ffmpeg_transport.py` if native FFmpeg is unavailable.

**Interfaces:** Consume Task 1 selections/status. Preserve `ReelRenderer.render(build: ReelBuild, work_dir: Path, out_path: Path) -> Path` and `ReelClip` public fields. Multiple sections expand into consecutive `ReelClip` values with original media ID and distinct start/end/duration; renderer work filenames use segment index plus media ID.

- [ ] **Write failing tests through preview/render seams.** A recording `StubReelRenderer.calls` build must contain source-time-ordered sections with summed duration 16.0; source bytes remain unchanged. Old single-range manifest must preserve its previous digest until explicitly edited; edited ranges must change digest, mark output stale, and make an old review unapprovable. Cards appear once, not per section; no-audio clips still render silence.

```python
assert [(c.trim_start, c.trim_end) for c in build.clips] == [(0.0, 5.0), (10.0, 15.0), (24.0, 30.0)]
assert sum(c.duration for c in build.clips) == 16.0
```

Add a real render test with a six-second source containing distinct colored/audio regions, retaining `[0, 0.4)`, `[2, 2.4)`, `[4, 4.4)`. Assert approximately 1.2 seconds (`abs(actual - 1.2) < 0.15`), selected color order at output 0.1/0.5/0.9 seconds, non-silent audio, H.264/AAC, 1080x1920, watermark presence, and distinct intermediate files. Repeat with single-frame PNG intro/outro cards of 0.2 seconds each and assert total approximately 1.6 seconds/cards visible once. Also render an audio-less source retaining `[2, 2.4)` and assert a 0.4-second segment with AAC silence; nonzero source seek must not seek past the generated silent track. Call the production renderer, not a copied FFmpeg command.
- [ ] **Observe RED:** `uv run --project dojo-core pytest dojo-core/tests/test_render_selections.py -v` — old build or overwritten-segment output fails. If Docker/native FFmpeg is absent, record the integration blocker; still run recording-renderer tests.
- [ ] **Implement expansion/digest.** Include canonical selections only when present in the manifest, retain legacy digest input shape otherwise, and source `FPS` from `REEL_FPS`. Use segment indices for temporary names without changing media identity. Reuse the existing canvas/audio/branding pipeline. If needed, test-only `run_in_ffmpeg_container(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]` maps real subprocess transport and mounted paths/concat-list paths to `jrottenberg/ffmpeg:8-alpine`; it must not replace processing/filter behavior with a stub.
- [ ] **Observe GREEN/regressions:** `uv run --project dojo-core pytest dojo-core/tests/test_render_selections.py dojo-core/tests/test_render.py dojo-core/tests/test_review.py dojo-core/tests/test_review_resolution.py dojo-core/tests/test_ffmpeg_fixtures.py -v` — behavioral and real render checks pass; disclose skips.
- [ ] **Commit named files:** `feat(render): assemble retained video sections`.

### Task 3: Authoritative editor snapshots and private artifact resolution

**Files:** Create `dojo-core/src/dojo/package_media.py`, `dojo-core/tests/test_package_editor.py`; modify `dojo-core/src/dojo/model.py`, `__init__.py`, `publishing.py` (media toggles/completed browsing/download methods), and `dojo-core/tests/test_media_removal.py`.

**Interfaces:** Export frozen `PackageArtifact(path: Path, filename: str, content_type: str)` for transport only. Add `get_active_editor() -> dict`, `get_media_preview(media_id: str, *, expected_folder_name: str) -> PackageArtifact`, and `resolve_completed_artifact(folder_name: str, artifact_ref: str) -> PackageArtifact`. Extend `browse_completed_package(folder_name: str) -> dict` additively with artifact descriptors. Descriptor keys: `artifact_ref`, `kind` (`original`/`processed`/`render`), `filename`, `content_type`, `available`; URLs belong to API translation.

- [ ] **Write failing read/lifecycle tests.** Snapshot fields are `package` (public package data), `render_stale`, `media` (original entry metadata plus `is_video`, `source_duration`, `effective_duration`, `preview_ref`, `artifacts`), `montage` (Task 1 status). Verify finalized/removed previews use their actual storage location while existing manifest fields remain intact. Removal/restoration invalidate render; active reads do not create absent packages. Completed reads do not change manifest bytes.

```python
artifact = seam.resolve_completed_artifact(completed.folder_name, f"removed/{video}/original.MP4")
assert artifact.path.read_bytes() == original_bytes
assert artifact.filename == "Çalışma.MP4"
```

Also test removed-selection survival, Unicode/no-extension originals, unavailable processed/render files, unknown references, `../`, absolute paths, and symlinks escaping media root (skip symlink creation only if platform privileges prevent it, recording why). Reject active packages through completed resolver.
- [ ] **Observe RED:** `uv run --project dojo-core pytest dojo-core/tests/test_package_editor.py -v` — missing snapshot/resolver failures.
- [ ] **Implement private descriptors/resolution.** `describe_artifacts(root: Path, manifest: dict) -> list[dict]` and `resolve_artifact(root: Path, manifest: dict, artifact_ref: str) -> PackageArtifact` in `package_media.py` recognize canonical originals/processed files beneath known media IDs/statuses and `render/reel.mp4`; never arbitrary directory browsing. Original suffix comes from preserved filename or supported MIME fallback. Resolve both package root and candidate and enforce containment/file existence. Keep metadata path-only internally; facade output contains relative references. Preserve source files/ranges on toggle and clear `render_revision` after successful toggle.
- [ ] **Observe GREEN:** `uv run --project dojo-core pytest dojo-core/tests/test_package_editor.py dojo-core/tests/test_media_removal.py dojo-core/tests/test_selections.py -v` — all pass.
- [ ] **Commit named files:** `feat(core): expose private package artifacts`.

### Task 4: Typed authenticated API, generated contracts, and browser transport

**Files:** Create `backend/src/backend/routes/package_models.py`, `backend/tests/test_package_editor_api.py`; modify `backend/src/backend/routes/packages.py`, `backend/scripts/generate_clients.py`, `backend/tests/test_contract.py`, `web/src/api/client.ts`, `web/src/api/client.test.ts`; regenerate `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt`.

**Interfaces:** Pydantic DTO names: `VideoRangeOut`, `SelectionIn`, `MontageOut`, `PackageArtifactOut`, `EditorMediaOut`, `ActiveEditorOut`, `CompletedPackageOut`. `SelectionIn` has `expected_folder_name: str` and `selections: dict[str, list[VideoRangeOut]]`. `ActiveEditorOut` has `package: PackageOut`, `render_stale: bool`, `media: list[EditorMediaOut]`, `montage: MontageOut`; media preserves existing raw fields (including processed metadata/removed position) and adds Task 3 metadata, `preview_url: str | None`, `artifacts: list[PackageArtifactOut]`. Artifact DTO extends Task 3 descriptor with `url: str | None`. `CompletedPackageOut` preserves `folder_name`, `media`, `order`, `caption`, `render_revision`, and adds top-level `artifacts`.

- [ ] **Write failing endpoint/transport tests.** Use a local app fixture like `test_publication_api.py`, including real `HmacSignedUrlStore`. Verify auth/browser-cookie/device/revoked cases, missing package, identity mismatch, invalid selections (422), limit/legacy conflict (409), and no writes on rejected requests. Preview returns real processed bytes and byte ranges (`Range: bytes=0-3` yields 206/exact bytes). Downloaded original/removed/render bytes and attachment filenames are correct; authenticated URLs never use `/pub/`. Test a rollover between snapshot and selection/order/removal requests returns 409; legacy requests without optional guards still work. Existing public raw-media denial remains.
- [ ] **Observe RED:** `uv run --project backend pytest backend/tests/test_package_editor_api.py -v` and, from `web/`, `npm test -- src/api/client.test.ts` — endpoint/client failures, not fixture setup failures.
- [ ] **Implement DTOs/routes/client methods.** Add authenticated `GET /active/editor`, `PUT /active/selections`, `GET /active/media/{media_id}/preview?expected_folder_name=...`, and `GET /{folder_name}/artifacts?artifact_ref=...&download=true|false` beneath `/api/packages`. Order body gains optional `expected_folder_name`; removal/restoration accept it as an optional query value. Map Task 1 errors to 409, existing range errors to 422 and missing data to 404. File delivery has `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, actual MIME, and safe inline/attachment disposition. Existing POST download uses Task 3 resolver and returns same-origin authenticated `{url}` without calling `create_download_url`/Meta signer; preserve legacy core method for existing callers.

Browser methods on `api`: `packageEditor(signal?) -> Promise<ActiveEditorOut>`, `saveSelections(body: SelectionIn, signal?) -> Promise<MontageOut>`, `saveOrder(order: string[], expectedFolder: string, signal?) -> Promise<MontageOut>`, `removeMedia(id: string, expectedFolder: string, signal?) -> Promise<void>`, `restoreMedia(...) -> Promise<void>`, `completedPackages(signal?) -> Promise<PackageOut[]>`, `completedPackage(folder: string, signal?) -> Promise<CompletedPackageOut>`. URL-encode all folder/media/reference values. Add new DTO roots explicitly in the TypeScript generator; Kotlin remains the existing compatibility artifact, with no new Android UI/version policy.
- [ ] **Regenerate and observe GREEN:** run `uv run --project backend python backend/scripts/export_openapi.py`, then `uv run --project backend python backend/scripts/generate_clients.py`; run `uv run --project backend pytest backend/tests/test_package_editor_api.py backend/tests/test_contract.py backend/tests/test_publication_api.py -v`; from `web/`, run `npm test -- src/api/client.test.ts` and `npm run typecheck`. Regenerate a second time; generated-file diff must not change.
- [ ] **Commit named source/tests/generated files:** `feat(api): expose package editor contracts`.

### Task 5: Draft-safe live editor state and navigation ownership

**Files:** Create `web/src/packages/ranges.ts`, `ranges.test.ts`, `usePackageEditor.ts`, `usePackageEditor.test.tsx`, `PackageEditorProvider.tsx`, `PackageEditorProvider.test.tsx`; modify `web/src/navigation.ts`, `web/src/App.tsx`, `web/src/i18n/tr.ts` and affected App/upload navigation test fixtures.

**Interfaces:** Export `VideoRange = VideoRangeOut`, `SelectionMap = Record<string, VideoRange[]>`, and `RangeInput = { start: string; end: string }`. Pure helpers: `validateRanges(ranges: VideoRange[], duration: number) -> string | null`, `retainedDuration(ranges: VideoRange[], duration: number) -> number`, `addRangeAtPlayhead(ranges: VideoRange[], playhead: number, duration: number) -> VideoRange[] | null`, `proposedDuration(snapshot: ActiveEditorOut, draft: SelectionMap) -> number | null`. `usePackageEditor() -> PackageEditorState` exposes `snapshot`, `draft`, `draftInputs: Record<string, RangeInput[]>`, `validationErrors: Record<string, string>`, `dirty`, `stale`, `offline`, `busy`, `error`, `setRanges(id, ranges)`, `setInput(id: string, index: number, bound: "start" | "end", value: string)`, `save(): Promise<boolean>`, `discard()`, `refresh()`, `reorder(order): Promise<boolean>`, `remove(id): Promise<boolean>`, `restore(id): Promise<boolean>`. Numeric draft ranges are derived only from valid inputs; invalid/partial text stays in session-owned `draftInputs`, marks dirty, makes proposed total unavailable, and blocks save. `PackageEditorContext = PackageEditorState & { requestLeave(): Promise<boolean> }`; `usePackageEditorContext()` returns that context.

- [ ] **Write failing tests for drafts and lifetime.** Test saving all videos together; empty client list omits its key; total is 16 for the approved example, and unknown duration returns null. Test lost response preserves draft, flags uncertain state, requires explicit refresh, and sends no automatic duplicate PUT. Rollover or late old-package responses never update the new snapshot. On 401 invalidate session/clear drafts; on ordinary network failure retain readable data. Unrelated refresh preserves dirty values; changed media/order/sections marks stale and blocks writes. Remove A with unsaved changes needs save/discard/cancel; discarding A does not discard B's draft.

```ts
expect(api.saveSelections).toHaveBeenCalledWith({ expected_folder_name: folder, selections: { a: rangesA, b: rangesB } }, expect.anything());
expect(state.dirty).toBe(true); // lost response, not false success
```

Provider tests navigate away with dirty edits: cancel stays on package; discard permits navigation; save permits navigation only after acknowledged success. Partial invalid numeric input survives closing/reopening a video editor, blocks save, and cannot be silently lost on navigation. `beforeunload` warns about remaining dirty drafts. Preserve upload queue/file references across navigation.
- [ ] **Observe RED:** from `web/`, `npm test -- src/packages/ranges.test.ts src/packages/usePackageEditor.test.tsx src/packages/PackageEditorProvider.test.tsx` — named behavior fails.
- [ ] **Implement state/guard.** Use existing five-second `startLiveRefresh`, session generation/invalidation, abort signals and single-flight writes. Compare relevant authoritative media/order/selection fields, not unrelated dashboard timestamps. Exclude removed IDs from active PUT while backend preserves their selections. Wrap `PairedShell` with `PackageEditorProvider` inside the existing session/onboarding boundary; leave its outer `UploadProvider` lifetime unchanged. Extend `useNavigation(canLeave?: () => Promise<boolean>)` to return existing route fields plus `navigate(href: string): Promise<boolean>`; `PairedShell` passes context `requestLeave` and uses guarded navigation for shell links. Reject/restore external hash navigation before disposing drafts. Use an accessible save/discard/cancel dialog and `beforeunload`, not silent reset.
- [ ] **Observe GREEN/regressions:** from `web/`, run focused tests, `npm test -- src/App.test.tsx src/uploads/UploadFlow.test.tsx src/session.test.tsx`, and `npm run typecheck` — all pass.
- [ ] **Commit named files:** `feat(web): preserve package editing drafts`.

### Task 6: Accessible visual timeline and precise video controls

**Files:** Create `web/src/packages/RangeTimeline.tsx`, `RangeTimeline.test.tsx`, `VideoSectionEditor.tsx`, `VideoSectionEditor.test.tsx`; modify `web/src/packages/ranges.ts`, `web/src/i18n/tr.ts`, `web/src/styles.css`.

**Interfaces:** `RangeTimeline({ duration: number, ranges: VideoRange[], playhead: number, disabled: boolean, onChange(ranges: VideoRange[]): void, onSeek(seconds: number): void })`; `VideoSectionEditor({ media: EditorMediaOut, ranges: VideoRange[], inputs: RangeInput[], validationError: string | null, disabled: boolean, onChange(ranges: VideoRange[]): void, onInputChange(index: number, bound: "start" | "end", value: string): void })`. Empty client ranges mean whole-video mode; timeline gestures emit sorted valid ranges, while exact fields send raw text through Task 5 state. The parent owns draft inputs/persistence; these components send no mutation requests.

- [ ] **Write failing interaction tests.** Track bounding-box fixture must turn drag 0–5/10–15/24–30 on 30-second source into the approved ranges; handle resize changes corresponding exact field. Test click-to-seek versus drag-to-select, pointer capture/cancel restoring old values, keyboard steps 0.1/1, bounds/min-frame/gap/neighbor clamping, pointer events inside media rows not triggering reorder, preview error/retry, unavailable duration, last-section removal showing whole-video mode, and no network writes on drag.

```ts
expect(screen.getByText("Yalnızca seçili bölümler kullanılacak.")).toBeInTheDocument();
expect(screen.getByRole("slider", { name: /1\. bölüm başlangıcı/i })).toHaveAttribute("aria-valuenow", "10");
expect(screen.getByLabelText(/1\. bölüm bitişi/i)).toHaveValue(15);
```

- [ ] **Observe RED:** from `web/`, `npm test -- src/packages/RangeTimeline.test.tsx src/packages/VideoSectionEditor.test.tsx` — intended interaction assertions fail.
- [ ] **Implement timeline/video controls.** Use pointer capture, a six-pixel click/drag threshold, track-local touch-action, clamped time geometry and accessible slider handles. Numeric fields are controlled by Task 5 raw draft inputs; show field-specific errors and prevent save until valid, including when the current editor closes. Native `<video controls playsInline preload="metadata">` uses `preview_url`, maintains playhead, and seeks without fetching blobs. Add uses Task 5 range helper; unavailable sub-frame gaps leave ranges unchanged. Preserve focus when deleting sections. Use existing tokens, tabular times, selected-range labels/borders beyond color, and stacked mobile layout with at least 44px controls; no thumbnail/waveform generation.
- [ ] **Observe GREEN:** from `web/`, run focused tests and `npm run typecheck`; no mutation on gesture, correct ARIA values/focus, all pass. Real geometry/mobile/seek checks follow in Task 8.
- [ ] **Commit named files:** `feat(web): add multi-range video timeline`.

### Task 7: Active media management and read-only completed browsing

**Files:** Create `web/src/packages/ActivePackagePanel.tsx`, `ActivePackagePanel.test.tsx`, `CompletedPackages.tsx`, `CompletedPackages.test.tsx`, `PackageManager.tsx`, `PackageManager.test.tsx`; modify `web/src/components/PackageSummary.tsx`, `web/src/i18n/tr.ts`, `web/src/styles.css`, `web/src/App.test.tsx`, `web/src/uploads/UploadFlow.test.tsx`, `web/src/test/fixtures.ts` as needed.

**Interfaces:** `ActivePackagePanel()` consumes Task 5 shared state, composes media rows/Task 6 editor and `UploadPanel`; `CompletedPackages({ onBack(): void })` uses Task 4 list/detail methods with local read-only selection; `PackageManager()` switches active/completed views through draft guard. `PackageSummary` retains page heading, review-gone messaging and pending actions while composing `PackageManager`.

- [ ] **Write failing end-user tests.** Remove then restore visibly moves media without deletion and shows render stale; drag drop and up/down actions persist expected identity/order and revert display on rejection. Only one video preview mounts at once while other videos retain local drafts; total/over-limit/unknown-duration states are distinct. Save all video sections, remount/reload, and see persisted ranges. Upload-finalization refresh appends new media without erasing dirty edits and warns when relevant snapshot changed. Completed mode loads without an active package; download links use authenticated URLs with encoded Unicode names, missing artifacts are unavailable, late old-folder detail responses are ignored, and completed mode contains zero mutation/upload controls. Ongoing uploads remain scoped to active package through completed browsing.

```ts
expect(screen.queryByRole("button", { name: "Bölümleri kaydet" })).not.toBeInTheDocument(); // completed view
expect(screen.getByRole("link", { name: /orijinali indir/i })).toHaveAttribute("href", authenticatedArtifactUrl);
```

- [ ] **Observe RED:** from `web/`, `npm test -- src/packages/ActivePackagePanel.test.tsx src/packages/CompletedPackages.test.tsx src/packages/PackageManager.test.tsx` — visible workflow fails.
- [ ] **Implement composition.** Separate finalized ordered media from removed rows, use explicit drag handles and keyboard alternatives, and prevent timeline gestures from starting media drag. Display backend limit/excess and client proposed total with field errors/unknown state; save stays disabled while invalid/stale/offline/busy. Removal of a dirty video asks save/discard/cancel before submitting. Move `UploadPanel` into active composition only; do not remount outer upload provider. Completed view uses processed/native render previews and direct authenticated attachment links, never Meta public URLs or download blobs. Keep all authored copy in `tr.packageManagement` and existing semantic layout/styles.
- [ ] **Observe GREEN/regressions:** from `web/`, run focused tests, `npm test`, `npm run typecheck`, and `npm run build` — new package flows and existing pairing/onboarding/uploads pass.
- [ ] **Commit named files:** `feat(web): manage active and completed media`.

### Task 8: Real-browser regression checks, CI, and verification evidence

**Files:** Create `web/playwright.config.ts`, `web/e2e/package-management.spec.ts`, `web/e2e/fixtures/timeline.mp4`, `docs/verification/issue-29-web-media-management.md`; modify `web/package.json`, `web/package-lock.json`, `web/vitest.config.ts`, `.github/workflows/ci.yml`, `.gitignore`, `README.md`.

**Interfaces:** Add development-only `@playwright/test` (latest Node 22-compatible stable version when execution begins, recorded by lockfile), `test:browser = "playwright test"`, Chromium `desktop` (1280x900) and `mobile` (390x844, touch-enabled) projects, `testDir: "./e2e"`, `baseURL: "http://127.0.0.1:3000"`, Vite webServer `npm run dev -- --host 127.0.0.1 --strictPort`, and `reuseExistingServer: !process.env.CI`. Limit Vitest inclusion to `src/**/*.test.{ts,tsx}` so browser specs are not collected. Ignore Playwright reports/test-results; retain only synthetic fixture media.

- [ ] **Write failing browser tests and needed test-only setup together.** Generate a deterministic small 30-second/160x90/25fps H.264 MP4 fixture with FFmpeg using synthetic content, not dojo media. Route paired/setup/dashboard/editor/list/detail API calls to deterministic public-contract fixtures; preview route serves actual MP4 bytes with valid byte ranges. Tests use pointer geometry to create/resize sections, cancel a gesture, use keyboard/exact fields, seek actual video, save/reload, drag reorder on desktop, use move buttons/touch handles on mobile, remove/restore, and browse read-only downloads. For mobile drag/cancel, use `context.newCDPSession(page)` with `Input.dispatchTouchEvent` start/move/end/cancel on actual track coordinates; do not bypass pointer-capture behavior with synthetic DOM events. Assert no horizontal overflow at both viewports and visible focused controls; fail on unhandled page errors or unexpected API calls.
- [ ] **Observe RED:** at execution time and from `web/`, run `npm install --save-dev @playwright/test`, `npx playwright install chromium`, and `npm run test:browser` — existing missing/incorrect interaction assertions fail. Keep unit tests green after test-runner separation.
- [ ] **Resolve actual browser defects and wire CI.** Fix only observed scope defects using owning components, rerun their unit tests, add web CI `npx playwright install --with-deps chromium` followed by `npm run test:browser`, and preserve existing npm test/build steps. Confirm real video seeking against Task 4 backend range tests. Run one desktop/mobile screenshot/accessibility inspection batch, fix all observed issues together, and confirm at most once; no open-ended polishing.
- [ ] **Run final verification.** Commands below must pass; real FFmpeg/browser checks must execute rather than silently skip. Document exact commands, results/skips, commit, and remaining environment blockers in verification evidence. Update README package workflow and link evidence without implying unrelated #30/#35 work is complete.

```text
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
uv run --project worker pytest worker/tests -v
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project backend ruff check backend/src backend/tests
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend mypy backend/src/backend
uv run --project backend python backend/scripts/export_openapi.py
uv run --project backend python backend/scripts/generate_clients.py
```

From `web/`: `npm test`, `npm run typecheck`, `npm run build`, `npm run test:browser`. From repo root: `git diff --check` and inspect generated diffs for determinism. Run Impeccable detector once over changed UI targets; security/privacy and critical accessibility findings block completion. Never claim a missing Docker/media/browser check passed.
- [ ] **Commit named setup/tests/docs and actual defect fixes:** `test(web): verify package timeline workflows`. Request the execution method's required independent review, resolve substantiated findings, rerun affected verification, then present integration options without pushing/merging/closing the issue autonomously.

## Plan Self-Review and Approval

- [x] Spec coverage: active lifecycle/order (1, 3, 7), retained sections/duration/cards (1–2, 5–6), private artifacts (3–4, 7), compatibility/digest (1–2, 4), drafts/navigation/staleness (5, 7), browser/actual render/contract verification (2, 4, 8).
- [x] Step scan: each task has a named interface, behavioral red check, implementation scope, green command, and scoped commit; setup belongs to its tested deliverable.
- [x] Type consistency: facade `VideoSelections`, API `SelectionIn`/`MontageOut`/`ActiveEditorOut`, and browser `SelectionMap` carry the same retained interval representation and identity field.
- [x] Review focus: all five listed failure classes have explicit owning test steps.
- [x] Proportion: decisions/signatures/tests are specified; no copied product implementation bodies.
- [ ] User reviews this plan and chooses Native or Subagent-driven execution. Product implementation remains blocked until that response.
