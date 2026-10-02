# Issue #29: Web Media Management and Multi-Range Timeline

Date: 2026-10-02
Issue: https://github.com/35HaRRy/aisomedo/issues/29
Parent: #1, Dojo Reel Publishing MVP
Blockers: #9, #10, and #27 are closed.

## Intent and approval boundary

Dojo administrators need to prepare an Aktif Paket without losing source media: remove and restore items, persist montage order, retain selected video sections, understand duration limits, and browse/download historical Tamamlanmış Paket contents.

The user added multiple retained sections per video, then approved the proposed behavior with a visual timeline alongside precise start/end controls. This document records that conversational design approval. Written-spec review and implementation-plan review remain separate gates; no product implementation has started.

Success means the saved selections, displayed duration, and rendered content agree. Original files remain unchanged, and completed packages remain immutable.

## Selected approach

Extend the existing package screen and deep `DojoPublishing` facade. Use a visual timeline plus a retained-section list, not browser-side exports or a separate video-editing subsystem. Keep business validation, persistence, duration accounting, and rendering behind the backend seam.

Alternatives considered:

- Numeric range list alone: smaller UI, but the user selected a visual timeline as well.
- Browser-side cuts uploaded as new files: duplicates media and splits editing authority; rejected.
- Full nonlinear editor with independently reorderable sections, transitions, and multiple tracks: unnecessary for this issue.

## User-visible behavior

### Active package and montage order

- Preserve package metadata, uploads, pending actions, existing navigation, and onboarding.
- Show finalized media in manifest order, with filenames, previews, effective durations, and removal actions.
- Persist drag ordering on drop. Provide named move-up/move-down buttons for keyboard and touch users. New uploads continue to append.
- Keep removed media in a separate section with a restore action. Removal never deletes the original or processed files. Restore uses the existing saved-position behavior and restores retained-section metadata.
- Explain that edits make the current render stale; do not automatically render after every edit.

### Video timeline and retained sections

- Open one video editor at a time below its media row. The editor has a native video preview, playback position, time ruler, selected-section track, precise range fields, and section add/remove controls.
- Drag over unselected timeline space to create a section. Click without dragging seeks the preview. Each retained section has draggable start/end handles; selecting its body selects that section rather than changing montage order.
- Pointer interactions support mouse, pen, and touch. Capture the active pointer so dragging remains stable outside the track; canceling a gesture restores its previous values. Preserve normal page scrolling outside the editing track.
- Provide keyboard-operable handles with accessible names, values, and limits. Arrow keys adjust by 0.1 seconds, Shift+Arrow by 1 second, clamped to legal bounds. Exact numeric inputs remain an equivalent non-drag interaction.
- “Bölüm ekle” seeds a section at the playhead in a free gap, initially one second or the remaining gap if shorter. If no usable gap exists, explain why without changing the selection.
- Display retained sections in source-time order. Sections within one video are not independently reorderable. The montage order controls the position of the video as a whole.
- Only retained sections appear in the rendered Reel. Their source audio is retained. Unselected material is not included, but remains in the original file.
- No selection means the whole video. Removing the last selected section returns to whole-video mode and explicitly says so. Excluding the whole video uses the media removal action.
- Videos with missing or invalid duration cannot be edited; show an actionable unavailable state rather than guessing bounds.
- Label selection semantics directly: “Yalnızca seçili bölümler kullanılacak.”

### Saving and duration limits

- Timeline edits are local drafts until “Bölümleri kaydet.” Display saved/unsaved state separately from render-stale state.
- Allow drafts across several videos and submit active-video selections together. This lets the administrator correct an over-limit package in one operation rather than getting blocked after each individual video.
- Show the proposed total while editing, alongside the backend limit and the seconds that must be removed. Count active photos, selected video sections, and enabled intro/outro cards using the same rules as the render build.
- Backend rejection writes nothing. Keep the draft and show the reason with a clear correction action. Never silently truncate or split a Reel.
- Existing over-limit rejection for order changes remains. Explain that duration must be reduced before saving a new order. Removal/restoration retain their existing lifecycle behavior; any resulting over-limit state is visible and blocks rendering.

### Completed packages

- Place a completed-package browser within the package area, independent of whether an active package exists.
- List completed packages and load the selected package's contents, including retained media, removed media, and available final renders.
- Use authenticated processed-media previews and final-render previews when those artifacts exist. Offer downloads for original media, processed media, and final renders; originals remain downloadable even when their format is not browser-previewable.
- Show missing artifacts as unavailable, not as broken download links.
- Never show upload, remove, restore, order, or section-edit controls for a Tamamlanmış Paket. Viewing a completed package does not redirect the active upload queue into it.

## Selection model and compatibility

Introduce an additive manifest field, `selections`, mapping media IDs to arrays of retained ranges:

```json
{
  "selections": {
    "video-id": [
      {"start": 0.0, "end": 5.0},
      {"start": 10.0, "end": 15.0},
      {"start": 24.0, "end": 30.0}
    ]
  }
}
```

- Endpoints are seconds in the processed source video, with start inclusive and end exclusive.
- Every endpoint is finite and satisfies `0 <= start < end <= source_duration`. Reject sections shorter than one output frame (currently 1/25 second).
- Sort by start time before persistence. Reject duplicate or overlapping ranges rather than silently merging them. Adjacent ranges are allowed.
- An omitted ID means full video. Empty arrays are invalid API input; the browser omits the ID when returning to whole-video mode.
- Only finalized videos can receive new selections. Reject unknown IDs, removed targets, non-video targets, and invalid duration metadata with explicit errors.
- Replacing active-video selections preserves stored selections for removed media, so restore does not lose prior editing choices. New uploads have no selection and use their full duration.
- Older active manifests without `selections` normalize existing `trims[media_id] = {start, end}` into one retained interval in memory. This matches the existing renderer's actual output, not the inconsistent old duration calculation. Reading does not rewrite historical manifests.
- Existing legacy trim request/response fields remain single-range objects. Add normalized `selections` to montage/editor responses rather than changing the shape of `trims`.
- New writes store canonical selections and keep a single-range legacy projection where representable. A legacy full-replacement trim write is rejected with 409 if it would overwrite existing multi-range selections; return a clear instruction to use an updated editor. Legacy single-range writes otherwise remain supported and synchronize both representations.
- Keep legacy trim data for removed items when projecting or synchronizing active selections.
- Completed manifests and rendered artifacts are never migrated, rewritten, or re-rendered by browsing.

### Superseded duration decision

The earlier issue #10 design states `source_duration - (end - start)`. Existing rendering instead keeps `start..end`. A diagnostic using a 30-second source and a 10–20-second range confirmed that status reports 20 seconds while the renderer requests 10 seconds.

This design supersedes that duration decision for editable packages: selected-video duration is the sum of retained interval lengths. An unselected video uses full source duration; photos use configured photo duration. Optional cards count once, using the render build's asset and duration rules. All status, mutation validation, render-limit checks, and render construction consume the same normalized selection interpretation.

## Backend responsibilities and API

Keep routes thin. Facade operations own lifecycle checks, selection validation, artifact resolution, persistence, render invalidation, and audit attribution. A focused internal montage helper may hold normalization and duration rules without introducing a second public facade.

### Read model

Add `GET /api/packages/active/editor`, authenticated, returning a typed snapshot with:

- Package identity/status and render-stale state.
- Finalized and removed media metadata, normalized selections, preview references, and available artifacts.
- Explicit order and typed montage status, including source/effective durations and duration-limit feedback.

Do not infer removed media from the upload queue. Do not expose server-absolute paths. Metadata and processed-video duration refer to the same artifact used for preview and rendering.

Retain existing completed-list and completed-detail endpoints; add typed artifact descriptors and preview references without removing existing detail fields. Artifacts have a package-relative reference, kind, display filename, content type, and authenticated URL.

### Selection mutation

Add `PUT /api/packages/active/selections` with package identity and the full active-video selection map. Validate every selection and the resulting duration before writing any changes. Return normalized montage status. On success, clear render revision and any failed-render suppression tied to old inputs as existing edit behavior requires, and append an actor-attributed audit event.

The new editor supplies expected package folder identity on every mutation. Extend existing order/removal/restoration routes with backward-compatible optional identity guards. Reject a mismatched active package with 409 rather than applying an old screen's action to a replacement package. This is not a new cross-device compare-and-set revision protocol; existing backend coordination remains authoritative.

### Private previews and downloads

- Add authenticated active-media preview delivery resolved by package/media identity and manifest state.
- Add authenticated completed-artifact delivery at `GET /api/packages/{folder_name}/artifacts`, taking an artifact reference and an optional attachment flag.
- Resolve only known manifest originals/processed files and the known final-render artifact. Reject path traversal, escaped/symlink-resolved paths, and unknown references. Verify the package is completed for completed-artifact delivery.
- Stream via the existing file-response approach, with appropriate content type, safe display filename, private/no-store caching, and inline versus attachment disposition. Preview seeking must work against byte-range requests.
- Preserve the existing `POST /api/packages/{folder_name}/download` response shape `{url}` but return an authenticated same-origin artifact URL. Browser download uses that URL directly, not a large blob buffered in JavaScript.
- Do not use or loosen `HmacSignedUrlStore` for administrator media downloads. Its public `/pub/{token}` flow must remain scoped to the approved render only; it intentionally rejects raw media.
- Browser cookies and device credentials retain equal access; unauthorized or revoked requests are denied.

Use explicit Pydantic schemas for new editor, range, selection, montage, and artifact contracts. Regenerate committed OpenAPI, TypeScript, and Kotlin artifacts through the existing generation flow. Do not hand-edit generated models.

## Rendering

- Normalize each video's selections behind the publishing seam, then expand its retained sections into ordered `ReelClip` render segments. Unselected videos and photos remain one segment each.
- Each video section carries its own start, end, and effective duration. Use unique per-section work names so multiple sections from one media ID cannot overwrite each other's temporary output.
- Preserve the existing 1080x1920 canvas, blurred fit, source audio/silence handling, watermark, and optional cards. Cards wrap the entire montage, not each retained section.
- Include canonical selections in the render-input digest. Changing any range invalidates stale output and existing approval binding through the established digest flow.
- Preserve the existing digest-input shape for legacy manifests until an explicit edit introduces canonical selections. Reading an old manifest must not invalidate a pending review solely by adding an empty selection field to the digest.
- Rendering remains explicit/on-due. No exports in the browser and no new automatic render-on-drag jobs.

## Frontend structure and state

Preserve the incumbent white/gray surfaces, teal accent, system font, Turkish copy, responsive shell, and existing spacing patterns. This is an Operate surface, not a visual redesign.

- `PackageSummary` composes active media management and completed browsing alongside existing uploads and pending actions.
- A package-editor state owner handles authoritative snapshots, local selection drafts, save status, errors, and refresh.
- A video-section editor owns preview and timeline interactions; a small pure range helper handles source-order sorting, bounds, and proposed duration. Backend repeats all validation.
- Reuse the session-aware request layer and live-refresh lifecycle. Abort loads on unmount or package changes, ignore late responses, and invalidate the session on authorization loss.
- Background refresh never silently replaces dirty drafts. If authoritative selections/order/media changed, show that the package changed and require refresh/discard before saving. Mere unrelated dashboard updates must not erase drafts.
- Disable mutations while offline, stale, loading, saving, or no longer active. Keep readable data and give retry/refresh actions. Do not automatically retry an uncertain write.
- Removal of a video with unsaved section edits warns that those local edits will be discarded. Switching packages or leaving the editor with dirty drafts requires an explicit save/discard/cancel choice.
- On narrow screens, stack preview, timeline, and range controls; keep times readable and actions at least 44px. No whole-page horizontal overflow. Full editor behavior remains available without pointer precision.
- Use meaningful focus management, visible focus, live save/error announcements, labeled native controls, and non-color-only range selection. Do not announce every pointer movement.
- Load one video preview on demand with metadata preload; avoid decoding every package video or building thumbnail strips/waveforms for this issue.

## Error contract

- 401: unauthorized/revoked client; follow existing session invalidation.
- 404: missing active package, media, completed package, or artifact; refresh and explain unavailability.
- 409: completed/ineligible package mutation, package-identity mismatch, duration limit, or incompatible legacy write; preserve drafts and show the specific corrective action.
- 422: invalid order or range data, unsupported target type, overlap, non-finite endpoints, or invalid duration bounds; identify the offending video/range.
- Network, preview-decoding, and download failures remain distinct. Preview failure does not report that a save failed, and a save failure does not delete existing media.

## Verification and acceptance

Use tests at the existing `DojoPublishing` behavioral seam rather than tests of private helper calls. Add thin API and client tests plus actual FFmpeg fixtures where media output matters.

1. Remove/restore preserves originals, processed media, stored sections, saved position, and stale-render behavior; newly uploaded media appends to explicit order.
2. Drag and keyboard order persist after reload; failed writes retain authoritative order and show failure.
3. A 30-second source with ranges 0–5, 10–15, and 24–30 yields 16 seconds of retained video, in that order. Mixed photo/video/card duration agrees with the render build.
4. Invalid/overlapping/too-short sections, unknown IDs, removed targets, and non-video targets are rejected without partial persistence or misleading success.
5. Multi-video selection saves can bring an over-limit package under the limit; rejected saves preserve both backend state and local correction drafts.
6. Legacy single-range manifests preserve existing rendered selection meaning, while old destructive full-replacement writes cannot erase multi-range selections.
7. Range edits change render digest and invalidate prior output/approval binding. Real FFmpeg tests verify section order, duration with frame/codec tolerance, output metadata, audio, and branding.
8. Timeline pointer creation/resizing/cancel, keyboard controls, exact inputs, full-video reset, and save/reload are covered. Use a real browser for pointer geometry and video seek behavior, not only DOM mocks.
9. Refresh, upload completion, package rollover, offline state, unauthorized responses, and late requests never silently apply edits to the wrong package or erase dirty drafts.
10. Completed packages browse and download original, processed, removed, and rendered artifacts without edit controls or manifest mutation. Verify actual authenticated file delivery, traversal denial, revoked-client denial, and continued denial of public raw-media exposure.
11. Regenerated contracts, backend/domain tests, web tests, typecheck/build, and bounded desktop/mobile accessibility/visual checks pass before claiming completion.

## Out of scope

- Android media-management UI (#35); only shared contract generation changes here.
- Review-flow UI (#30), caption/branding editors, scheduling, and publication recovery.
- Timeline thumbnails, audio waveforms, transitions, effects, multitrack editing, or independent section reordering.
- Source-file rewriting, browser-side exports, automatic splitting, or automatic truncation.
- Historical package migration or re-rendering, a new public-media channel, or a new general concurrency subsystem.

## Review status

Conversational design approved with the visual-timeline addition. The user approved the written specification ("uygun"). Implementation plan: `docs/superpowers/plans/2026-10-02-web-media-management-timeline.md`; plan review and execution-method selection remain pending. Product changes have not begun.
