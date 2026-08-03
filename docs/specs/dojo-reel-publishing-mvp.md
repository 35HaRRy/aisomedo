# Dojo Reel Publishing MVP

## Problem Statement

Dojo administrators collect photos and videos from classes, but preparing and publishing them consistently to Instagram is manual, error-prone, and easy to postpone. Media can be duplicated, ordered incorrectly, lost between devices, rendered differently from its preview, or published twice after a network failure. A biweekly publishing cadence also requires someone to remember the correct Monday, prepare a branded Reel, review it, handle missed approvals, and confirm whether Instagram accepted it.

Administrators need one reliable workflow that stores the current `Dojo Paylaşım Paketi`, turns its ordered media into an exact branded Reel, requests review at the right `Yayın Zamanı`, safely publishes the approved artifact through Instagram's official interface, and preserves an auditable history. They need this workflow from Android and the web without maintaining user accounts, while still preventing unauthorized access and conflicting actions across devices.

## Solution

Provide an always-on dojo publishing system with a Kotlin Android application, a responsive web dashboard, and a FastAPI backend running on a Linux VPS. Administrators pair trusted Android devices and browsers without creating user accounts. Both clients manage the same active `Dojo Paylaşım Paketi`, including resumable media uploads, filename conflict resolution, ordering, trimming, caption editing, branding, final preview, scheduling, and review.

A dedicated worker evaluates the `Dojo Yayın Planı`, renders an immutable 1080x1920 Reel with the mandatory dojo watermark, and creates a `Yayın İncelemesi`. All posts require approval in the MVP. Administrators can approve, skip, or reschedule the current `Yayın Zamanı`; the first valid action across equal devices wins. Approval publishes the exact reviewed artifact through the official Instagram Graph API. Safe retry logic prevents duplicate posts, and a package becomes a `Tamamlanmış Paket` only after Instagram confirms publication.

## User Stories

1. As a dojo administrator, I want to pair my Android device once without creating an account, so that I can securely administer the system without recurring login prompts.
2. As a dojo administrator, I want to pair a browser once without creating an account, so that I can use the full dashboard securely from a computer.
3. As a dojo administrator, I want to pair multiple equally privileged devices, so that trusted dojo staff can manage the same publishing workflow.
4. As a dojo administrator, I want to see all paired devices and browsers, so that I know which clients can control publication.
5. As a dojo administrator, I want to revoke a paired client, so that a lost or retired device can no longer access dojo content.
6. As a dojo administrator, I want pairing codes to expire after one use and a short period, so that leaked bootstrap codes cannot be reused.
7. As a dojo administrator, I want to connect one Instagram Professional account through the official Meta authorization flow, so that the system can publish without storing my Meta password.
8. As a dojo administrator, I want to see the connected Instagram account name and connection health, so that I can verify the publication target.
9. As a dojo administrator, I want to reconnect Instagram when authorization expires or refresh fails, so that publishing can resume without losing the active package.
10. As a dojo administrator, I want guided first-run setup, so that pairing, Instagram connection, schedule, consent policy, logo, caption template, and optional cards are complete before scheduling starts.
11. As a dojo administrator, I want to accept the media-consent policy once per policy version, so that responsibility for publishing student media is explicit and auditable.
12. As a dojo administrator, I want one active `Dojo Paylaşım Paketi`, so that all new dojo media has one unambiguous destination.
13. As a dojo administrator, I want the system to create an active package when none exists, so that first use does not require filesystem administration.
14. As a dojo administrator, I want the system never to maintain more than one active package during normal operation, so that media cannot be published from the wrong batch.
15. As a dojo administrator, I want package folders named with portable 24-hour timestamps, so that archives work consistently across filesystems.
16. As a dojo administrator, I want to upload photos and videos from Android, so that class media can be added directly from a phone.
17. As a dojo administrator, I want to upload photos and videos from the web dashboard, so that desktop media can be added without transferring it to a phone.
18. As a dojo administrator, I want large uploads to resume after interruption, so that mobile network failures do not restart an entire video transfer.
19. As a dojo administrator, I want upload progress, pause, and retry controls, so that I understand and control long transfers.
20. As a dojo administrator, I want partially uploaded files excluded from the active package until validation completes, so that corrupt media cannot enter a Reel.
21. As a dojo administrator, I want common Android image and video formats accepted, so that I rarely need to convert media manually.
22. As a dojo administrator, I want unsupported or invalid media rejected with a clear reason, so that I can correct the file before review.
23. As a VPS operator, I want configurable per-file and per-package upload limits, so that storage policy matches server capacity.
24. As a dojo administrator, I want the app to reject an oversized upload before transfer begins, so that time and bandwidth are not wasted.
25. As a dojo administrator, I want Unicode filenames, including Turkish characters, preserved safely, so that media remains recognizable.
26. As a dojo administrator, I want path characters, control characters, and portable case-insensitive collisions handled safely, so that filenames cannot escape or corrupt package storage.
27. As a dojo administrator, I want to choose what happens for each duplicate filename, so that I retain control over conflicting media.
28. As a dojo administrator, I want a keep-both action that selects the first available numeric suffix, so that neither file is overwritten.
29. As a dojo administrator, I want a keep-selected action that replaces the existing target after an irreversible warning, so that deliberate overwrite remains possible.
30. As a dojo administrator, I want a keep-target action that ignores the selected upload, so that existing media remains unchanged.
31. As a dojo administrator, I want to apply one conflict decision to all compatible conflicts, so that bulk uploads remain efficient.
32. As a dojo administrator, I want true overwrites recorded in the audit history, so that destructive exceptions remain traceable.
33. As a dojo administrator, I want to remove media from a montage without deleting its file, so that accidental removal is reversible.
34. As a dojo administrator, I want removed media retained inside the package and restorable while it is active, so that source files are never lost through normal removal.
35. As a dojo administrator, I want completed package contents to become read-only, so that publication history cannot drift from what was posted.
36. As a dojo administrator, I want to browse and download completed package media and renders, so that I can inspect or reuse historical material.
37. As a dojo administrator, I want to order media explicitly, so that the Reel follows the intended narrative rather than filesystem order.
38. As a dojo administrator, I want newly uploaded media appended to the explicit order, so that existing sequencing remains stable.
39. As a dojo administrator, I want to trim videos when the combined duration exceeds Instagram limits, so that I control which content is removed.
40. As a dojo administrator, I want the system to block over-limit montages rather than truncate them silently, so that no media disappears unexpectedly.
41. As a dojo administrator, I want photos to have a configurable default duration, so that still images remain visible long enough in the Reel.
42. As a dojo administrator, I want each video clip's original audio retained, so that class sound remains part of the montage.
43. As a dojo administrator, I want nonvertical media fitted inside a 9:16 frame with a blurred background, so that people are not cropped automatically.
44. As a dojo administrator, I want every Reel to include the configured dojo logo watermark in a safe area, so that publication is consistently branded.
45. As a dojo administrator, I want optional global intro and outro cards, so that I can add branded framing when desired.
46. As a dojo administrator, I want to override intro and outro defaults for one package, so that exceptional posts can use different framing.
47. As a dojo administrator, I want a reusable caption template, so that recurring posts start with consistent copy.
48. As a dojo administrator, I want to edit the copied caption during review without changing the global template, so that one-off changes do not affect future packages.
49. As a dojo administrator, I want template replacement fields to be configurable later, so that the initial release does not lock in an incomplete field vocabulary.
50. As a dojo administrator, I want media edits to mark the current render stale, so that I cannot mistake an old preview for current content.
51. As a dojo administrator, I want rendering to begin when I request preview or when a publication becomes due, so that server resources are not wasted after every edit.
52. As a dojo administrator, I want to preview the final 1080x1920 publish-ready file, so that the reviewed output exactly matches the posted output.
53. As a dojo administrator, I want approval bound to the exact media, order, trims, branding, caption, and render revision, so that unseen edits cannot be published under an old approval.
54. As a dojo administrator, I want a dashboard showing the active package, next `Yayın Zamanı`, pending action, Instagram health, and worker health, so that current status is immediately clear.
55. As a dojo administrator, I want separate Current Package, Activity, and Settings areas, so that routine tasks remain easy to locate.
56. As a dojo administrator, I want a focused review flow opened from the dashboard or notification, so that I can make a publication decision with full context.
57. As a dojo administrator, I want a `Dojo Yayın Planı` with an explicit first date, local time, and `Europe/Istanbul` timezone, so that alternating Mondays are deterministic.
58. As a dojo administrator, I want to change the recurring plan settings, so that future publication times reflect dojo operations.
59. As a dojo administrator, I want a manual publish action, so that I can prepare an extra Reel between regular slots.
60. As a dojo administrator, I want manual publication not to shift the recurring plan, so that extra posts do not disturb the established cadence.
61. As a dojo administrator, I want every scheduled or manual Reel to require review in the MVP, so that no public content is posted unseen.
62. As a dojo administrator, I want a due `Yayın Zamanı` to create one durable `Yayın İncelemesi`, so that restarts and repeated scheduler checks do not create duplicate requests.
63. As an Android administrator, I want a push notification when review is required, so that I do not need to keep the application open.
64. As a web administrator, I want the dashboard to update while open, so that I can see due reviews and other-device actions without refreshing manually.
65. As a dojo administrator, I want Review, Skip, and Reschedule choices for a due publication, so that I can respond appropriately when timing or content is not ready.
66. As a dojo administrator, I want Review to open the exact Reel and caption before approval, so that publishing cannot happen accidentally from the lock screen.
67. As a dojo administrator, I want Skip to require confirmation and show the next regular time, so that I do not suppress reminders accidentally.
68. As a dojo administrator, I want Skip to keep the same active package and stop reminders until the next regular slot, so that unfinished media remains available.
69. As a dojo administrator, I want Reschedule to require a future local date and time, so that the same package can be reviewed at a deliberate one-off time.
70. As a dojo administrator, I want a new reschedule to replace the previous one-off time, so that one package cannot have conflicting reminders.
71. As a dojo administrator, I want rescheduling not to shift the recurring plan, so that one exception does not redefine all future Mondays.
72. As a dojo administrator, I want configurable reminder frequency and quiet hours, so that pending review remains visible without overnight disruption.
73. As a dojo administrator, I want reminders to stop after approve, confirmed skip, or reschedule, so that resolved reviews do not continue notifying me.
74. As a dojo administrator, I want an empty active package to offer Upload Media, Skip, and Reschedule, so that a due slot does not become a dead end.
75. As a dojo administrator, I want uploading from an empty-package notification to return to render and review, so that the same flow can continue.
76. As a dojo administrator, I want late approval to publish immediately, so that missing the original time does not require rebuilding the package.
77. As a dojo administrator, I want the first valid action across equal devices to win atomically, so that approvals, skips, and reschedules cannot conflict.
78. As a dojo administrator, I want stale notifications and screens dismissed or refreshed after another device acts, so that all clients show the authoritative result.
79. As a dojo administrator, I want a clear "already handled by another device" response, so that a rejected stale action is understandable.
80. As a dojo administrator, I want approval to claim the package with a `-publishing` state before external work begins, so that concurrent jobs cannot publish it twice.
81. As a dojo administrator, I want Instagram to fetch only the approved render through a short-lived signed URL, so that raw dojo media stays private.
82. As a dojo administrator, I want the system to save Instagram container and media identifiers, so that uncertain network responses can be reconciled safely.
83. As a dojo administrator, I want definite pre-publication failures to return the package to an editable active state, so that I can retry or change it.
84. As a dojo administrator, I want uncertain Instagram outcomes polled before retry, so that a timeout cannot create a duplicate Reel.
85. As a dojo administrator, I want Retry, Review, Skip, and Reschedule options after a definite publication failure, so that recovery fits the situation.
86. As a dojo administrator, I want all paired Android devices notified of publication success or failure, so that staff know the outcome.
87. As a dojo administrator, I want the package renamed `-completed` only after Instagram confirms publication, so that completed history always means publicly posted.
88. As a dojo administrator, I want the system to create a new empty active package immediately after successful completion, so that the next upload destination is ready.
89. As a dojo administrator, I want skipped, rescheduled, failed, cancelled, and authorization-blocked packages to remain incomplete, so that no unpublished package appears successful.
90. As a dojo administrator, I want the newest unsuffixed folder selected if corruption creates several open folders, so that recovery follows a deterministic rule.
91. As a dojo administrator, I want older open folders renamed `-recovered` without deleting contents, so that the one-active-package invariant is restored safely.
92. As a dojo administrator, I want to import recovered media into the active package through normal conflict handling, so that stranded files can rejoin the workflow.
93. As a dojo administrator, I want a resolved recovered folder marked separately, so that the same media is not imported twice accidentally.
94. As a dojo administrator, I want a full audit history of uploads, conflicts, edits, reviews, device actions, state transitions, Instagram identifiers, and failures, so that every publication can be reconstructed.
95. As a dojo administrator, I want audit entries to identify the paired client responsible for an action, so that equal-device operation remains accountable without user accounts.
96. As a dojo administrator, I want recent activity visible in Android and web clients, so that routine diagnosis does not require VPS access.
97. As a dojo administrator, I want cached package and activity data viewable when Android is offline, so that I can inspect recent state without connectivity.
98. As a dojo administrator, I want uploads to pause and resume after Android reconnects, so that offline transitions do not lose transfer progress.
99. As a dojo administrator, I want mutations disabled while Android is offline, so that stale approvals or edits cannot conflict with backend state.
100. As a VPS operator, I want the backend, worker, database, media volume, and reverse proxy deployed together, so that production operation is reproducible.
101. As a VPS operator, I want scheduler leadership restricted to one worker, so that multiple processes cannot emit duplicate publication work.
102. As a VPS operator, I want health checks, structured logs, disk-space alerts, failed-job alerts, and external HTTPS monitoring, so that operational failures are visible.
103. As a VPS operator, I want manual encrypted backup and restore commands covering database, configuration metadata, and media, so that I can move recoverable archives off-server.
104. As a VPS operator, I want completed media retained indefinitely unless I deliberately change policy later, so that publication evidence and source files remain available.
105. As a developer, I want one generated OpenAPI contract for Kotlin and TypeScript clients, so that client models and backend behavior do not drift.
106. As a developer, I want the backend to support the current and immediately previous Android release, so that service deployment does not instantly break manually updated clients.
107. As an Android administrator, I want the app to identify an unsupported version and direct me to a signed update, so that incompatibility is explicit.
108. As an Android administrator, I want signed APK releases available through GitHub Releases, so that the small trusted admin group can install updates without a public store launch.
109. As a maintainer, I want merges to `main` to deploy backend, worker, and web services only after all checks pass, so that production stays current without manual service deployment.
110. As a maintainer, I want a pre-deployment database snapshot, migration preflight, health verification, and container rollback, so that automatic deployment fails safely.

## Implementation Decisions

- Build one single-context monorepo containing backend, Android, web, and operations modules. Shared client artifacts are generated from the backend's OpenAPI contract.
- Keep all business rules in an always-on backend. Android and web clients are administration interfaces; they do not own scheduling, rendering, or publication state.
- Run FastAPI as the public application process and a dedicated Python worker as the scheduler/render/publication process. Persist schedules and jobs in PostgreSQL and use database coordination so one scheduler owns due-time emission.
- Place the primary module seam at a deep `Dojo Publishing` interface used by both FastAPI routes and scheduler triggers. It owns package lifecycle, media decisions, review resolution, rendering orchestration, publication recovery, and audit behavior.
- Deploy on one Linux VPS with Docker Compose, PostgreSQL, a durable media volume, worker, FastAPI process, web frontend, and HTTPS reverse proxy.
- Use React and TypeScript for a responsive full-parity web dashboard. Use Kotlin and Jetpack Compose for Android 10 and newer, with portrait-first phone UI and adaptive tablet behavior.
- Provide Dashboard, Current Package, Activity, and Settings navigation in both clients. Review is a focused flow reachable from Dashboard, Activity, and notifications where supported.
- Do not create user accounts. Pair Android devices and browsers with short-lived one-time codes. Issue revocable device credentials; browser credentials use secure, HttpOnly cookies. All paired clients have equal permissions.
- Deliver Android notifications through FCM and maintain a durable in-app approval inbox. The web dashboard receives live in-app updates while open but does not use background Web Push in the MVP.
- Resolve concurrent review actions with revision-aware atomic compare-and-set behavior. First valid action wins; later clients receive an already-handled result and refresh stale state.
- Connect one Instagram Professional account linked to a Facebook Page through browser-based Meta OAuth. Store long-lived tokens encrypted on the backend and expose only connection status to clients.
- Refresh Meta authorization before expiry. Failed refresh blocks publication, preserves the active package and schedule state, and asks administrators to reconnect.
- Use the official Instagram Graph API only. Do not use browser automation.
- Keep backend filesystem storage authoritative for package media. All normal changes occur through the backend interface; direct VPS filesystem editing is unsupported.
- Represent a `Dojo Paylaşım Paketi` as one folder plus a manifest. The manifest holds immutable media identifiers, explicit order, source metadata, trims, caption, branding choices, render revision, Meta identifiers, and recovery information.
- Use `dd-MM-yyyy HH-mm` in `Europe/Istanbul` for portable package folder names. An unsuffixed folder is active, `-publishing` is claimed or externally uncertain, `-completed` is confirmed published, `-recovered` is excluded corruption recovery, and `-resolved` indicates recovered media has been handled.
- Enforce zero or one active package during normal operation. Create an active package on first upload/setup if absent and immediately after confirmed publication.
- If startup discovers multiple unsuffixed folders, choose the newest timestamp as active, atomically rename older ones `-recovered`, preserve all contents, notify administrators, and audit the repair.
- Import recovered media only through the active package's regular conflict workflow. Never publish a recovered folder directly.
- Accept JPEG, PNG, WebP, HEIC/HEIF, MP4, and MOV uploads. Validate actual content, normalize images, and transcode video to Instagram-compatible H.264/AAC. Reject animated images, invalid media, and unsupported codecs with actionable errors.
- Implement resumable chunked uploads with checksums, progress, pause/retry, and temporary-upload cleanup. Finalize media into the active package only after complete validation.
- Default upload limits to 2 GiB per file and 20 GiB per active package, configurable by the VPS operator. Check declared size before transfer and actual size/disk availability during finalization.
- Preserve safe Unicode display filenames. Reject path separators and control characters, normalize names for portable case-insensitive conflict checks, and use immutable manifest media IDs.
- For filename conflicts, support keep both, keep selected, and keep target per file plus compatible apply-to-all behavior. Keep both uses the first free numeric suffix. Keep selected is a true destructive overwrite with target preview, explicit irreversible warning, and audit record.
- Normal media removal never deletes the source file. Move it under package-local removed storage, exclude it from montage, permit restoration while active, and retain it read-only after completion.
- Completed packages are immutable and browse/download-only. Originals, removed media, manifest, and final render are retained indefinitely in the MVP.
- Save explicit montage order in the manifest and append new uploads. Do not infer order from filenames, upload timestamps, or filesystem enumeration.
- Render one Reel rather than a carousel. Fit non-9:16 media into a 9:16 canvas using a blurred background, preserve original video audio, and use configurable image duration.
- If combined duration exceeds current Instagram/API limits, require the administrator to trim or remove media. Never silently truncate or automatically split a package into multiple Reels.
- Apply a mandatory configured dojo logo watermark in the bottom-right safe area of every frame. Support optional global intro/outro assets and durations copied into each draft and overridable per package.
- Maintain a global caption template copied into each draft and editable per package. Replacement field names remain intentionally undecided until a later configuration decision.
- Mark a render stale whenever its media, order, trims, branding, or caption changes. Render on explicit Preview or when a `Yayın Zamanı` becomes due, not after every edit.
- Produce the final 1080x1920 publish-ready MP4 before review. Bind `Yayın İncelemesi` and approval to a digest of all inputs and the immutable output. Publish exactly that reviewed artifact.
- Configure `Dojo Yayın Planı` with `Europe/Istanbul`, explicit first date, local Monday time, and biweekly recurrence. Manual publication and one-off rescheduling never shift the recurring anchor.
- Every scheduled and manual publication requires approval in the MVP. There is no unattended auto-publish option.
- A due time creates at most one durable `Yayın İncelemesi` for the active package revision. Repeated scheduler evaluation and process restarts are idempotent.
- Pending-review notifications offer Review, Skip, and Reschedule. Review opens exact media and caption. Skip requires confirmation and displays next regular occurrence. Reschedule accepts one future local date/time and replaces any prior one-off.
- Skip keeps the same active package, stops reminders for the current occurrence, and waits for the next regular occurrence. Reschedule keeps the package, restarts reminders at the replacement time, and leaves recurring cadence unchanged.
- If the active package is empty at due time, offer Upload Media, Skip, and Reschedule. Upload continues with rendering and review for the same package.
- Configure reminder interval and quiet hours, defaulting to every six hours between 08:00 and 22:00 in `Europe/Istanbul`. Stop reminders when the review is approved, skipped, or rescheduled.
- Late approval publishes immediately. It does not create another folder or another review.
- Before publication, atomically rename the active folder `-publishing` and persist the approved revision and Meta operation identifiers.
- Expose only the approved render to Meta through an unguessable short-lived signed HTTPS URL. Log fetch access and revoke the URL after ingestion; never expose raw package media publicly.
- On definite failure before Meta acceptance, return the package to active state and offer Retry, Review, Skip, and Reschedule. On uncertain or accepted outcomes, retain `-publishing`, poll saved Meta identifiers, and prohibit a fresh publish until reconciled.
- Rename to `-completed` only after Meta confirms Reel publication. Immediately create one new empty active package using completion time.
- Keep a structured append-only audit history for pairing, uploads, conflicts, edits, reviews, actions, state transitions, Meta identifiers, signed-media access, failures, recovery, and policy acceptance. Attribute client actions to paired device identity.
- Android is read-only while offline except for pausing/resuming transfer state. Cached package and activity data remain viewable; edits and review actions require authoritative backend connectivity.
- Use one installation-wide media-consent policy acceptance per policy version. Store accepted version, timestamp, and accepting device; newly paired clients inherit current acceptance.
- Provide manual encrypted CLI backup and restore operations covering PostgreSQL, configuration metadata, and all media. Operators move archives off-server; no in-app backup UI or scheduled backup is included.
- Provide lean production monitoring: container health checks, structured logs, disk-space alerts, failed-job alerts to Android devices, and an external HTTPS uptime check. Do not deploy a full metrics platform in the MVP.
- Generate Kotlin and TypeScript clients from FastAPI OpenAPI in CI. Treat schema drift or stale generated clients as a failed check.
- Support the current and immediately previous Android release at the backend interface. Expose minimum supported version and block only incompatible clients with an update prompt.
- Build signed Android APKs and attach release builds to GitHub Releases. Do not include Google Play distribution in the MVP.
- Run backend, worker, web, Android, OpenAPI compatibility, FFmpeg fixture, and container-build checks in GitHub Actions. Merges to `main` automatically deploy backend, worker, and web after a PostgreSQL snapshot, migration preflight, health check, and rollback-capable release. Android distribution remains separate.
- Use Turkish as the initial UI language while externalizing all Android, web, notification, and backend user-facing strings for later localization.

## Testing Decisions

- Use one primary behavioral seam: the deep `Dojo Publishing` module interface consumed by FastAPI and scheduler adapters. Tests should assert externally visible domain outcomes through this interface, not private methods, database query shape, FFmpeg command construction, or internal call order.
- Exercise the primary seam with real PostgreSQL, real package filesystem behavior, and small deterministic FFmpeg media fixtures. Replace only genuinely variable external dependencies with adapters: Meta publishing, notification delivery, wall clock, and signed URL delivery.
- Cover the complete package lifecycle: absent package creation, upload finalization, ordering, removal/restoration, conflict decisions, rendering, revision invalidation, review creation, approve/skip/reschedule, publication claim, success completion, and next-package creation.
- Cover folder-state invariants through observable package outcomes: zero/one active folder, atomic `-publishing` claim, confirmed-only `-completed`, newest-open recovery, `-recovered` import, and no false completion after failure.
- Cover duplicate filename behavior including repeated numeric suffixes, portable case-insensitive collisions, Unicode names, keep-target, keep-both, destructive overwrite confirmation, bulk decisions, and overwrite audit records.
- Cover resumable upload behavior including interruption, duplicate chunk submission, checksum mismatch, oversize rejection, temporary-file cleanup, and exactly-once finalization.
- Cover montage behavior with deterministic fixtures for mixed images/video, explicit order, trims, blurred fit, mandatory watermark, optional cards, original clip audio, duration-limit rejection, and output metadata.
- Verify that preview and publication use the same immutable render digest. Editing any review input must invalidate the previous approval and prevent publication of stale content.
- Cover scheduling with a fake clock across anchor dates, alternate Mondays, manual publication, late approval, quiet hours, skipped occurrences, replacement reschedules, process restarts, and unchanged recurring cadence.
- Cover multi-device concurrency by racing approval, skip, and reschedule commands against one review revision. Assert one winner, deterministic stale responses, notification dismissal/update, and one publication claim.
- Cover empty-package due behavior and continuation after upload without creating a second active package.
- Cover Meta recovery with adapters that model definite rejection, timeout before response, accepted container with delayed status, successful publication, token expiry, refresh failure, and repeated worker execution. Assert no duplicate external publication command after uncertain outcomes.
- Cover signed render access by verifying scope to one immutable artifact, expiry, revocation after ingestion, and denial of raw media paths.
- Cover pairing and authorization through public behavior: one-use expiry, revocation, equal permissions, secure browser session behavior, stale/revoked credential denial, and installation-wide policy acceptance.
- Cover audit behavior by asserting required facts are observable for destructive overwrite, review resolution, state transitions, Meta identifiers, recovery, pairing, and consent acceptance. Do not assert private event class names or storage layout beyond the specified folder contract.
- Add thin FastAPI/OpenAPI contract tests to verify route validation, authorization, error mapping, streaming/resumable behavior, and generated-client compatibility. Do not duplicate domain scenarios already covered through the primary seam.
- Add Android UI tests for guided onboarding, navigation, upload/conflict handling, offline read-only mode, notification deep links, exact review display, stale-action messaging, and update-required state.
- Add web UI tests for pairing, full-parity package management, drag ordering, resumable upload controls, review resolution, live stale-state refresh, activity, and settings.
- Add a small deployed-stack acceptance suite against production-like Docker Compose with real PostgreSQL, filesystem volume, worker, FastAPI, web, and FFmpeg. Use a fake Meta endpoint and notification collector; prove one full scheduled and one manual workflow.
- Add deployment verification for migration preflight, health checks, rollback after failed health, and preservation of package/media/database state.
- No prior automated-test patterns exist in this repository. Establish these seams as project precedent rather than inventing separate seams for each backend module.
- A good test describes administrator-visible or operator-visible behavior, controls time and external outcomes deterministically, and remains valid if internal module composition, SQL, rendering command structure, or framework wiring changes.

## Out of Scope

- Scheduled Entries mini-posts, including quotation ingestion, text-to-image generation, and alternating-Monday publication.
- Special-day Stories, lesson schedule Stories, student birthday Stories, and reposting permanent feed posts to Stories.
- Unattended auto-publish. Every MVP Reel requires `Yayın İncelemesi` and approval.
- Carousel feed posts or automatic splitting into multiple Reels.
- Instagram browser automation, password storage, or support for personal Instagram accounts that cannot use the official publishing interface.
- Multiple Instagram accounts, per-device roles, user accounts, passwords, approval quorum, or last-action-wins conflict handling.
- Background Web Push, email, or SMS notifications for web administrators.
- Direct filesystem editing as a supported administration workflow.
- Automatic deletion or retention expiry for completed media.
- Automated scheduled backups, cloud backup transfer, or in-app backup download.
- Full Prometheus/Grafana-style metrics infrastructure.
- Google Play Store distribution or automatic Android installation.
- Offline mutation queues for Android.
- Automatic face-aware cropping, Instagram music-library integration, uploaded background music, or silent automatic trimming.
- Final caption replacement-field vocabulary and production caption copy; these remain onboarding/configuration decisions.
- Multi-context domain architecture or speculative abstractions for deferred publication workflows.

## Further Notes

- Canonical domain language comes from the root glossary: `Dojo Paylaşım Paketi`, `Dojo Yayın Planı`, `Yayın Zamanı`, `Yayın İncelemesi`, and `Tamamlanmış Paket`.
- `Tamamlanmış Paket` always means Instagram-confirmed publication. Skip, reschedule, cancellation, render failure, authorization failure, and uncertain publication do not qualify.
- Initial schedule anchor/time, caption text and future replacement fields, logo asset, optional intro/outro assets, upload limits, reminder policy, consent text, and Instagram account are supplied through configuration or guided onboarding.
- Current repository contains requirements and domain documentation only. There is no implementation, test suite, ADR, Git metadata, or established code pattern to preserve.
- The confirmed testing strategy deliberately concentrates behavior behind one primary seam. Framework and client tests verify integration and presentation without reproducing the full state matrix.
