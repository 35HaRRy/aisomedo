# Issue #29 brainstorming checklist

Issue: https://github.com/35HaRRy/aisomedo/issues/29

Path: architectural. Extend the existing web package screen and publishing API to support media management and completed-package downloads without moving business rules into the browser.

## Intent

Administrators need reversible removal, persistent montage ordering, video trims, actionable duration-limit feedback, and read-only browsing and downloads of completed package media and renders. Preserve existing upload behavior, Turkish localization, authorization, and backend authority.

The user explicitly added multiple retained ranges per video to issue #29. Only selected ranges appear in the output, in source-time order. Original files remain unchanged. The user subsequently approved the proposed design with a visual timeline alongside the precise range controls. Written-spec and implementation-plan approval remain pending.

## Checklist

- [x] Explore project context, issue, blockers, and recent commits.
- [x] No unresolved visual-choice question required the optional browser companion; the user explicitly chose a timeline plus precise range controls.
- [x] Clarify trim intent: multiple selected ranges are retained, not removed.
- [x] Propose two or three approaches with trade-offs and recommendation.
- [x] Present design and obtain approval, including the user's visual-timeline addition.
- [x] Write and commit conversationally approved design specification; written-spec review remains pending.
- [x] Self-review specification for placeholders, contradictions, ambiguity, and scope; clarify browser previews and legacy digest compatibility.
- [x] Obtain user review and approval of written specification (user: "uygun").
- [x] Invoke writing-plans and write/self-review implementation plan.
- [ ] Obtain plan review and execution-method selection before implementation.

## Discoveries

- Blockers #9, #10, and #27 are closed. Working tree was clean at exploration start.
- `web/src/components/PackageSummary.tsx` currently shows package metadata, uploads, and pending actions.
- Existing package API supports removal, restoration, montage status, ordering, trims, completed browsing, and download URL requests.
- Montage status contains finalized ordered clips, not removed media. The API needs an authoritative active-media listing for restoration.
- Completed browsing returns media and a render revision, but not explicit downloadable render references.
- Backend trim duration calculation subtracts the selected interval, but `_build_reel` passes that same interval to the renderer as a retained window. A non-product diagnostic using existing code and intercepted subprocess commands confirmed a 30-second source with a 10–20-second selection reports 20 seconds while the render command requests 10 seconds. Duration calculation and render selection must agree; preserve historical completed artifacts unchanged.
- Order and trim writes reject over-limit results. A batch trim editor may be needed to submit enough reductions together.

## Approved conversational design

- Selected: a visual retained-range timeline per video, alongside add/remove controls and exact start/end inputs; the backend validates and stores selections, and the existing render pipeline renders each retained section in chronological order.
- Alternatives discussed: numeric range list only (smaller UI scope), or browser-side exports uploaded as new files (duplicates files and splits authority).
- Validate finite endpoints within source duration; reject overlapping or empty ranges. No selection means the full video; remove media to exclude a video entirely.
- Keep ordering at media level; sections within each video follow source time. Show selected duration and total montage duration, preserving source audio and mandatory branding.
- Submit all video selections together so over-limit packages can be corrected across multiple videos in one operation.
- Keep active and removed media distinct, with reversible removal/restoration. Completed-package browsing has no mutation controls and includes downloadable source media, removed media, and final renders.
- Add authenticated browsing/preview endpoints and explicit artifact references where existing APIs lack them; keep generated contracts synchronized and avoid breaking existing single-range clients.
- Verify domain behavior, API validation/authorization, web interactions and persistence, and actual multi-section FFmpeg output.

Written specification: `docs/superpowers/specs/2026-10-02-web-media-management-timeline-design.md`.

Implementation plan: `docs/superpowers/plans/2026-10-02-web-media-management-timeline.md`.

No product implementation has started; plan review and execution-method selection remain pending.
