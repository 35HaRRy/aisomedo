# Active Package Media Panel

Date: 2026-10-24
Status: Technical design sections approved in conversation; written specification awaiting user review

## 1. Intent and requirements authority

Make active-package media editing predictable and card-local in both web and Android applications. Users must be able to inspect original media, save or discard one card without affecting another card's draft, and distinguish a saved video's section preview from the saved package Reel.

The feature request and confirmed decisions are in `docs/active_package_media_panel.md`. Domain vocabulary is defined in `CONTEXT.md`. The latest user correction takes precedence: a due Yayın Zamanı automatically requests a current Reel for Yayın İncelemesi. Ordinary media edits alone must not automatically request a Reel.

Successful delivery means the two clients expose equivalent behavior, real FFmpeg output matches saved selections, and cancelled or superseded jobs cannot publish obsolete results. Existing authorization, draft durability, merge rules, live-connectivity restrictions, and publication approval remain intact.

Approval of this written specification permits implementation planning, not product-code execution. The implementation plan and execution method require separate review.

## 2. Scope and approach

Extend the existing edit-group API, PostgreSQL-backed package state, durable job queue, private artifact access, and live-state invalidation. Do not introduce a separate preview service, queue broker, client polling loop, or test framework.

An isolated preview service was considered but rejected: it adds deployment and coordination overhead without a demonstrated resource-isolation requirement. Rendering must remain worker-side; client-only playback of selected ranges does not satisfy the requirement for a saved generated preview.

Included:

- Per-card video selections and photo display durations, including local save/discard controls.
- Video thumbnails, original-media fullscreen viewing, and generated section previews.
- Actual cancellation of superseded section-preview work and fenced output publication.
- Separate saved-Reel panel, actual output duration, and explicit versus due-occurrence rendering rules.
- Timeline endpoint correctness and cross-client verification.

Excluded: unrelated refactoring, a general-purpose job-management subsystem, cross-device draft synchronization, new offline-editing behavior, and automatic publication without user approval. This work does not authorize deleting or resetting existing package data.

## 3. Current structure and change boundaries

- `web/src/packages/ActivePackagePanel.tsx` currently places package-wide save/discard controls and the Reel preview above the media list.
- `web/src/packages/usePackageEditor.ts` already tracks edit groups and supports `discard(id)`, but `save()` submits all draft groups and validates all draft inputs.
- `android/app/src/main/java/com/dojo/aisomedo/editor/MediaEditorState.kt` currently builds its editable input model around videos; photo-duration groups and card-local save/discard need equivalent support.
- `backend/src/backend/routes/packages.py` exposes the editor, grouped edits, media previews, and Reel commands. Existing media preview playback uses processed media rather than the uploaded original.
- `dojo-core/src/dojo/package_state.py` performs three-way group merging and separates content fields from derived document fields.
- `dojo-core/src/dojo/publishing.py` owns transactional edits, montage validation, job creation, artifact attachment, and review scheduling.
- `dojo-core/src/dojo/adapters/render.py` currently runs FFmpeg synchronously. Section-preview work needs a cancellable subprocess path.
- `dojo-core/src/dojo/adapters/db.py` and `memory.py` implement the existing job store. Extend both implementations consistently.
- `worker/src/worker/main.py` already claims jobs atomically. Its scheduler path must verify an actual due occurrence before requesting a stale Reel.

These boundaries should be extended rather than replaced. Existing generated API clients and contract tests must follow the API schema changes.

## 4. Card-local persistence and drafts

### Save

A card save sends exactly its `video:<media_id>` or `photo:<media_id>` group through the existing grouped edit command. Preserve package identity, baseline values, content-revision validation, lifecycle restrictions, and three-way conflict detection.

The candidate montage consists of the target card's proposed value plus every other card's current persisted value. Validate that result, including aggregate duration. An invalid or over-limit draft on another card must not prevent this save. The server remains authoritative if another client's intervening change makes the candidate invalid.

Saving or acknowledging one group must not delete, submit, or rebase away unrelated local edits. Preserve existing durable draft storage, reconnect reconciliation, and explicit conflict decisions. A lost or uncertain command response must be reconciled with the server rather than blindly replayed as a new render request.

Save is enabled only for a changed, valid card when the existing live-connectivity, persistence, identity, and command-safety requirements allow it. Discard is enabled only for a changed card when existing safety rules allow it; invalid input must still be discardable. No automatic photo-duration saving is introduced.

### Discard, collapse, and removal

- Discard resets only the target card to the current persisted value.
- Closing the video editor only collapses it. Retain its draft and show an unsaved-changes indicator on the collapsed card.
- Removing media with unsaved edits requires confirmation. Do not discard its draft before successful removal; a rejected or failed removal must preserve it.
- Successful removal discards that card's draft, cancels its preview work, and excludes the media from the montage. Other cards' drafts survive.
- Restoring media restores its persisted selections or photo duration, not its discarded draft.

### Selection semantics

Selected intervals describe retained footage, not footage to remove. Sort intervals chronologically before rendering. Reject non-finite values, overlaps, and intervals outside the source duration; retain the existing minimum duration of one frame at 25 FPS.

No selected intervals means the whole video participates in the montage. Persist this using the existing omission semantics, not an empty list that the renderer might interpret as zero clips. The separate remove-media command excludes the video.

## 5. Derived preview state and API contract

Maintain thumbnail and section-preview metadata separately from render-relevant media content, for example in top-level derived package-document maps keyed by media ID. Do not put preview progress inside the existing `media` content field: `content_fields()` currently treats that field as editable content.

A section-preview record identifies the current generation/job, its saved input identity, status, artifact reference when ready, and probed duration. The generation identity is unique to the request, not only a hash of ranges: an A-to-B-to-A sequence must not allow the first A job to attach its output to the latest A request.

The editor response exposes distinct fields for:

- Original-media URL and content type.
- Video-thumbnail URL and availability.
- Section-preview status (`missing`, `queued`, `processing`, `ready`, or `failed`), current generation, output URL when ready, and actual duration.
- Saved Reel output duration when a current ready render exists.

Keep existing processed-media preview fields available to existing consumers; never silently change their meaning to original or trimmed footage.

Extend the existing routes with authenticated original-media, thumbnail, and generation-bound section-preview reads, plus a card-local section-preview retry command. Retry identifies the expected package, media, and saved selection/generation; reject or refresh a stale request rather than rendering an unrelated newer selection without reconciliation. A retry never submits local draft inputs. Duplicate retries reuse the active equivalent job.

Original and generated artifacts must be resolved through a manifest-bound allowlist under the package directory. Preserve authentication, path containment, content types, private caching policy, and byte-range playback support. Do not accept arbitrary filesystem paths or introduce public signed media URLs.

Preview progress and artifact attachment update derived view state and existing live invalidations, not content revision. They must not invalidate the Reel or create edit conflicts. Reuse the current SSE invalidation/snapshot-refresh mechanism; do not add periodic client data polling. Existing offline and disconnected-live-state action gates remain authoritative.

## 6. Section-preview lifecycle and worker execution

### Transactional request

When persisted video sections actually change, one shared command transaction must:

1. Validate and persist the card edit.
2. Invalidate the old section-preview generation so its URL is no longer served as current.
3. Cancel previous queued or processing section-preview jobs for that media.
4. For a nonempty selection, create a new `section_preview` job and record its generation; for an empty selection, leave no section preview or replacement job.
5. Commit state, job changes, and live invalidation together.

An equivalent repeated save is a no-op; it does not repeatedly cancel or enqueue work. Apply the lifecycle at the shared domain write boundary so alternate supported selection-write paths cannot leave obsolete previews valid. Photo edits and montage reordering do not regenerate or cancel another video's section preview.

Add the smallest store operation and database uniqueness protection needed to enforce active job identity for a package/media generation. Extend the existing job table rather than adding a new queue. Database and in-memory implementations must agree on deduplication and terminal states.

Immediate preview generation means durable enqueueing during the save transaction. Execution uses existing worker capacity; it does not promise that an encoder starts before the save response returns.

### Execution and actual cancellation

Capture the persisted sections and immutable media input identity before encoding, then release the package lock. Use the same validated chronological intervals as the Reel builder, reading the existing normalized full-length media source used by that builder.

The section preview concatenates only that video's retained intervals, retaining their audio. Do not add package intro/outro assets or a logo. It is a section-selection preview, not a second full-package Reel. Reuse existing encoding and concatenation primitives where practical without forcing a duplicate Reel build or unrelated renderer refactor.

Use a cancellable FFmpeg subprocess path with periodic checks of the durable current job/generation. For a superseded running job, terminate its owned subprocess, wait for a bounded grace period, and kill and reap it if necessary. Apply cancellation to any long-running subprocess within this preview pipeline. A signal to an API-local thread is insufficient because API and worker run in separate processes.

Cancellation is a normal terminal outcome, not an encoding failure or an upload rejection. Both success and error handlers must recheck durable job state before writing status; neither may change a cancelled job back to done or failed. A database/control-check failure must not authorize publication of an unverified output.

### Fenced publication and cleanup

Write output to a job-private staging directory. Under a short package lock and command transaction, verify:

- The original package still exists and is active.
- The media still exists, remains eligible, and has the same source identity.
- The generation/job is still the currently requested one for this video.
- The persisted selection still matches the job inputs and the job has not been cancelled.

Only then publish a generation-specific artifact and attach its metadata. Do not fence on the package-wide content revision alone: another card's save or reordering must not invalidate this independent job.

All terminal paths clean up their own staging files. Superseded URLs must not serve obsolete files as current even if physical cleanup is delayed or an already-open player has buffered bytes. Package clearing, media removal, source replacement, and package lifecycle transitions must prevent late writes or recreation of deleted package artifacts. Preserve historical package/review artifact rules.

### Failure and retry

An encoding failure leaves the saved section edit intact. Do not restore the old preview. Expose a card-local error and retry action. Retry uses the latest persisted selection after validating the request identity, not newer local draft input. An empty saved selection has no section preview to retry.

Worker interruption must not attach a partial file or leave a permanently unusable preview. Integrate with existing job recovery where available; otherwise expose an interrupted generation as retryable after a bounded stale-job check, fencing the old generation before replacement. Do not add a general lease framework as part of this feature.

## 7. Thumbnail and original-media behavior

Generate a reusable video still in the worker, outside the request-serving path. New uploads generate it as part of processing; existing videos without a thumbnail receive deduplicated worker work when required by the active editor. Thumbnail metadata is derived state and must not invalidate the Reel.

Card-list loading fetches images/thumbnails, not full video files. A thumbnail failure shows a stable placeholder and does not reject a valid uploaded video or block selection saves.

Clicking a card's media image opens a fullscreen viewer. Videos use the uploaded original file; photos use their displayable image preview. Unsupported original video formats produce an explicit playback error rather than silently substituting a processed or trimmed video. The editor also retains the original-video player independently of the generated section preview.

The existing normalized media duration remains the authoritative selection bound used by both preview and Reel rendering. Metadata differences in original playback must not let clients submit endpoints outside that bound.

## 8. Web and Android presentation

### Active media panel

- Keep refresh and clear actions in their existing header location, but use accessible icon buttons. Preserve clear confirmation and cleanup retry behavior.
- Put the ordered uploaded-media list first in the panel's normal content; critical error and synchronization notices remain visible.
- Collapsed photo and video cards share a fixed height. Truncate filenames to one line, showing the full name through web `title` and Android's accessible/long-press equivalent.
- Use the photo label `Gösterilme süresi (sn)`.
- Put save/discard controls inside each card. In an expanded video card, place them immediately to the right of its close action. Remove package-wide save/discard controls and the unchanged-state text `Kaydedilecek değişiklik yok.`
- An expanded video card spans the complete row with no neighboring card beside it, grows with content, and preserves existing montage ordering and drag/reorder semantics.
- Show the original video above the generated section preview. Put each remove-section icon in that section row's upper-right corner.

Do not auto-expand or discard unrelated cards as a side effect of saving. Preserve the current single-expanded-editor interaction.

### Preview versus draft

While editing a card draft, retain the last saved section preview and indicate that it excludes unsaved changes. This includes clearing all sections in the draft. After a successful changed-section save, remove the old displayed preview, show queued/processing status, and display the new output only when ready. Saving an empty selection hides the section preview; keep the original player.

### Timeline

Support drag selection and endpoint adjustment through both exact `0` and exact source duration on web and Android. Preserve bounds after rounding, pointer/touch cancellation, nonoverlap, and minimum-frame validation. Ensure handles at the right edge are reachable rather than clipped. Numeric inputs remain available for precise and accessible editing.

### Fullscreen and accessibility

Provide meaningful icon labels, web tooltips, Android long-press explanations, loading/error announcements, and accessible disabled-state reasons. Fullscreen viewing supports explicit close, Escape or Android back, correct focus entry/containment/restoration where applicable, and player disposal on dismissal. Closing a viewer or editor must not discard draft edits.

## 9. Saved Reel and Yayın İncelemesi

Move the saved Reel preview to its own panel at the end of the current-package page, outside the active-media panel. Put the render icon in the upper-right header. The title shows the displayed rendered file's probed duration, not the proposed montage duration. Without a ready render, show `Henüz render edilmedi` instead of a duration; the missing-preview body says `Kaydedilmiş montajı henüz render edilmedi.` Queued, processing, and failed states remain distinguishable.

Unsaved edits do not invalidate the current saved Reel. If drafts exist, warn that the displayed Reel does not include them. Explicit rendering remains available with drafts, subject to saved-montage validity and existing safety gates; it uses only persisted inputs and leaves all drafts untouched.

A successful render-relevant content change invalidates the current saved Reel and removes it from display. It does not immediately enqueue a replacement merely because media changed. Existing immutable review artifacts must not be overwritten or deleted by active-preview cleanup.

The worker must distinguish these scheduling cases:

- **No due Yayın Zamanı:** do not enqueue a Reel merely because the saved montage is stale.
- **A due Yayın Zamanı and current ready Reel:** reuse it and continue the existing review flow.
- **A due Yayın Zamanı and no current ready Reel:** validate persisted inputs and automatically enqueue the needed Reel, reusing an equivalent active job. Do not incorporate drafts.

If saved inputs are invalid or rendering fails, do not create an approval-ready review for an absent or obsolete video. Preserve existing failure/retry safety. Successful rendering resumes the existing review flow, and publication still requires explicit user approval. Keep revision fencing for renders requested before later package changes.

## 10. Verification and acceptance

Use the existing Python, web, browser, and Android test infrastructure. No new test framework is required.

1. **Card isolation:** save/discard A preserves B's valid, invalid, and over-limit drafts. The server validates A against other persisted values and rejects an actually over-limit result without losing drafts.
2. **Draft durability:** close/reopen, reconnect, command uncertainty, and process restart preserve unrelated edits. Photo drafts behave consistently with video drafts on Android and web.
3. **Selection semantics:** empty selection retains the whole video; nonempty sections are chronological and identical between the section preview and Reel build.
4. **Transactional scheduling:** successful changed selection commits one current generation and job; rollback creates neither. Equivalent repeated requests and retries create no duplicate active work.
5. **Cancellation races:** superseding queued and processing jobs prevents old publication, including A-to-B-to-A selections and completion racing with cancellation. Verify termination of a real controllable subprocess, not only a cancellation flag.
6. **Independent jobs:** another media edit or order change does not cancel an otherwise current section preview. Derived completion does not change content revision or stale the Reel.
7. **Lifecycle races:** removal, source replacement, package clearing, and lifecycle transitions prevent obsolete output attachment and resurrection of deleted files. Failed removal preserves the local draft.
8. **Failure/retry:** preview failure preserves saved sections, removes no other card's output, and retries saved inputs without including drafts. Interrupted work has a bounded recovery/retry path.
9. **Actual montage output:** use a small deterministic video with distinguishable visual and audio sections, encode with real FFmpeg, and verify order, cuts, audio continuity, and measured duration within the encoder/frame tolerance. The selected start and terminal section must be identifiable; a mocked clip list alone is insufficient.
10. **Timeline edges:** mouse, touch, keyboard/numeric boundaries reach `0` and full source duration without rounding beyond it, overlap, or losing the final frame through an unreachable handle.
11. **Private media:** unauthenticated, wrong-package, traversal, removed/stale-generation, and unsupported-playback cases fail safely; current authorized playback and byte-range access work.
12. **Reel scheduling:** unsaved edits retain the Reel with a warning; saved changes invalidate it. A stale montage without a due occurrence causes no automatic render. A due occurrence creates/reuses the needed render and produces a review only for a ready current revision.
13. **Client presentation:** verify fixed collapsed heights, full-row expansion, one-line names, card-local icon states, original fullscreen media, preview placement, photo durations, end-of-page Reel panel, output duration, and accessible close/retry behavior on both clients.
14. **Regression:** regenerate and check API clients/contracts, run affected core/backend/worker tests, web typecheck/build/tests, and Android compilation and relevant unit/instrumented checks. Report environment-blocked checks explicitly rather than claiming they passed.

## 11. Handoff

All four technical design sections and the corrected due-occurrence render behavior were approved in conversation. This written specification must now be reviewed by the user. After approval, produce a file-specific, test-first implementation plan grounded in the actual call sites, including supported alternate mutation paths, database/index updates, generated contracts, and both clients.
