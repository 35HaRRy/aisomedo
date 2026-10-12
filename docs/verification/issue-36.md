# Issue 36: Android review, notifications, and deep links

Implementation branch: `feat/issue-36-android-review`, based on `43d74db`.
Verification date: 2026-10-11. No deployment, production push, merge, issue closure,
or remote branch update was performed.

## Automated evidence

Run from repository root unless a working directory is named below.
Python dependencies were installed with `uv sync --all-packages --frozen`.
Android used JDK 25 from Android Studio's `jbr`, an existing SDK, and Android 35.
Docker/PostgreSQL and the existing container FFmpeg fixtures ran locally.

| Command | Observed result |
| --- | --- |
| `uv run --project dojo-core pytest dojo-core/tests -v -rs` | 733 passed, 4 skipped |
| `uv run --project backend pytest backend/tests -v` | 209 passed |
| `uv run --project worker pytest worker/tests -v` | 140 passed |
| `uv run --project dojo-core ruff check dojo-core/src dojo-core/tests` | Passed |
| `uv run --project backend ruff check backend/src backend/tests backend/scripts` | Passed |
| `uv run --project dojo-core mypy dojo-core/src/dojo` | Passed, 34 source files |
| `uv run --project backend mypy backend/src/backend` | Passed, 23 source files |
| Android: `./gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest` | 161 unit tests after review fixes, 0 failures/errors; APK, lint, instrumentation APK compilation passed |
| Web: `npm ci`, then `npm test -- --maxWorkers=1` | 288 passed across 30 files; focused rerun passed 26 tests |
| Web: `npm run build` | TypeScript and Vite build passed |
| `uv run --project backend python backend/scripts/export_openapi.py` | 70 paths; no drift from committed OpenAPI |
| `uv run --project backend python backend/scripts/generate_clients.py` | Kotlin/TypeScript regeneration produced no drift |
| `uv run --project backend python backend/scripts/check_openapi_compat.py BASE_OPENAPI backend/openapi.json` | 0 breaking/unproven changes against `43d74db` |

To reproduce the compatibility baseline, export `43d74db:backend/openapi.json`
with `git show` into an owned temporary file and pass that path as `BASE_OPENAPI`.
On non-Windows hosts use `./gradlew` rather than `./gradlew.bat`.

Four existing core tests were skipped: one branding symlink test and one package
artifact symlink test require Windows symlink privileges; two direct media
processor tests require host `ffmpeg`/`ffprobe`. Container FFmpeg fixtures did run;
these four skips are not claimed as verified. CI already installs real media
tools and runs the affected suites, contract checks and Android instrumentation
compilation, so no duplicate CI job or Firebase credentials were added.

The first concurrent web run had 286 passes and two async wait timeouts:
`App.test.tsx`'s “resumes incomplete setup once and preserves intentional navigation”
and `SettingsSummary.test.tsx`'s “persists plan, branding and reminder edits across
a page remount”. Both passed in an isolated 26-test rerun; the complete suite was
rerun with one worker without source or timeout changes. `npm ci` also reported
six existing dependency vulnerabilities (2 moderate, 2 high, 2 critical); no npm
dependency was changed and no automatic audit fix was applied.

Baseline Android unit compilation was broken by two missing closing braces in
`DojoApiTest.kt`; those braces were restored before adding review behavior.
Existing Python SDK deprecation warnings and Android lint warnings remain;
lint has no blocking errors. FCM's old transitive Fragment dependency is
constrained to the Activity Result API's required minimum 1.3.0.

## Acceptance mapping

| Issue criterion | Runnable evidence | Remaining live/device evidence |
| --- | --- | --- |
| Notification opens exact review | `NotificationTargetTest`; `AppViewModelTest.notificationShortcutOpensFormWithoutPostingAndRejectsOldBinding`, `notificationVersionOrPackageMismatchCannotAuthorizeAnotherReview`, `oldTargetReadCannotReplaceNewReviewOrAuthorizeItsPreview`; `ReviewNotificationsTest` cold/warm/recreation cases | Real foreground/background/cold-start receipt and tap |
| Approve/skip/reschedule; handled messaging; inbox updates | `ReviewStateTest`; `DojoApiTest.reviewActionsUseDisplayedIdentityAndExplicitBodies`; `AppViewModelTest` decision, conflict, ambiguous mutation and session-binding cases; `test_empty_occurrence.py` includes PostgreSQL concurrency and rollback; focused backend API tests | Native screen/Back/date/time/accessibility checks |
| Review-required and outcome pushes | `test_fcm.py` checks real SDK data-only review/empty versus mixed outcome/monitoring messages; `test_empty_reminders.py` checks durable cadence; `PushRegistrationTest` tests real HTTP registration/rotation/retry/late failures; `ReviewNotificationsTest` checks notification construction/outcome launcher routing | Firebase/device delivery **not verified** |
| Empty notification → upload → render → same review | `AppViewModelTest` continuation cases (unresolved/foreign binding, worker-first, exact occurrence, retry, replacement, restoration); `test_empty_due_upload_renders_review_for_same_occurrence_and_package` verifies one package/occurrence/review; `ReviewContinuationTest` | Real picker/upload/conflict/render path **not verified** |

UI/player/notification instrumentation was compiled, **not executed**: `adb
devices -l` returned no device and `emulator -list-avds` returned no AVD. No
emulator, device, Firebase project, or credentials were provisioned. The one-second
6565-byte MP4 under Android test assets is synthetic, generated with the existing
`dojo.testing.render_test_clip` helper; no private media entered source control.

Preview transport tests cover authentication headers, redirect rejection,
streamed size bounds (small injected limit rather than allocating 512 MiB),
cancellation, cache-write failure, wrong revision and server/session switching.
The player uses app-private `review-previews` files, never an external Bearer URL;
only native player preparation enables Approve. Real codec/storage/device
behavior still needs instrumentation execution.

## Firebase operator setup

1. Use the existing Firebase project that matches the worker's `FCM_PROJECT_ID`
   and service-account project. Register Android application
   `com.dojo.aisomedo` in that project and download its `google-services.json`.
2. Place the file at `android/app/google-services.json` on each configured debug
   or release builder. It contains Firebase project/app identifiers, not a
   service-account private key; project convention still keeps it untracked.
   Never substitute or commit the backend service-account JSON.
3. Configure worker FCM using the existing deployment instructions in
   `docs/ops/deployment.md`: enable FCM, provide matching `FCM_PROJECT_ID` and
   `FCM_CREDENTIALS_FILE`/read-only service-account mount. Release builders also
   need the existing Android signing inputs. This document does not authorize
   deployment or live sends.
4. Install a configured build on a dedicated Android device with supported
   Google Play services. Pair it to the intended server and allow Android 13+
   notification permission from app Settings. Verify both system notification
   permission and the review channel remain enabled.
5. Missing Firebase configuration, unsupported services or denied permission
   does not remove Dashboard/Activity's durable approval inbox. Registration
   failures retry on the next active refresh. Token rotation is bound to captured
   origin/device credentials; old 401/426 responses cannot revoke a new session.

Google services plugin is pinned to `4.5.0`, Firebase BoM to `34.19.0`, with only
the main `firebase-messaging` module (no KTX/Analytics dependency). Plugin
application is conditional on the operator file. Both absent-config builds and
`processDebugGoogleServices`/APK builds with an owned synthetic config passed;
the synthetic file was removed afterward and the absent-config build rerun.
No real token was fetched in automated tests. Messaging auto-init defaults off;
the configured paired runtime enables it.

Default reminder window is 08:00 inclusive–22:00 exclusive in `Europe/Istanbul`,
every 360 minutes. Empty cadence is durable settings metadata keyed by exact
occurrence and package, not a second inbox database. It does not advance without
recipients or after a whole-send failure, and prunes resolved/replaced/nonempty
contexts. No named active package means no fabricated empty-package notification;
the normal inbox/package upload entry remains available. Notification shortcuts
open forms and never execute a command in the messaging service.

## Dedicated device checklist (not yet executed)

Run `./gradlew.bat :app:connectedDebugAndroidTest` on a dedicated **synthetic** test
emulator/device. Tests seed credentials/documents and must not run on a user's
production installation. Then, only with explicit operator authorization for
real Firebase sends:

- Receive review-required and empty-package messages foreground, background,
  and from a cold process. Repeat one payload: one notification per identity;
  Review/Upload, Skip and Reschedule retain their distinct destinations.
- Verify exact Reel/caption and controls before Approve; deny permission, disable
  the channel, and test missing/unsupported Play services while inbox stays usable.
- Cancel Skip and native date/time selection: no POST. Confirm Skip and future
  Istanbul Reschedule: inbox updates, cadence stays anchored, next regular time
  displays when available. Rotation/recreation must never replay decisions.
- Handle review on another device, then use old notification/version: show
  handled/stale explanation, do not silently open or approve a newer review.
- Empty-package Upload leaves picker/editor/conflict controls visible. Finish
  upload, resolve conflicts, render once and reach the same occurrence's review.
  Worker-first render must not enqueue another; failed render requires explicit retry.
- Switch server/session during delayed reads, preview or token registration:
  no old data/permission failure enters the new binding; private partial preview
  is deleted; old notifications and queued destinations clear.
- Receive confirmed/failed publication outcomes, including SDK background
  launcher extras: open Activity context for the named package, not active review.
- Check phone/tablet navigation, Back-to-owner, lifecycle polling stop on
  background/close, screen reader labels, font scaling, light/dark appearance,
  player decode errors and low storage.

Issue acceptance for real push receipt remains open until this checklist is run.

## Independent review and fixes

One fresh-context reviewer examined the whole implementation range
`43d74db..852bb36`. No Critical or Minor findings; seven Important findings entered
one test-first fix pass, committed as `6cc100e`. No second review or claim of
live-device acceptance.

| Finding | Regression evidence and resolution |
| --- | --- |
| Upload continuation could add media to a replacement package | `continuationSelectionRejectsStaleTargetAndReplacementDuringPicker`, `boundQueuedUploadCannotInitializeReplacementPackage`, `capturedPackageGuardSurvivesQueueReloadAndInitializationRace`: selection revalidates occurrence/folder; picker captures package ID; queued metadata retains `expected_package_id` across reload and rejects replacements. Selection also retains its session binding. |
| Historical preparing review could steal continuation | `preparingHistoricalReviewDoesNotStealContinuationFromReadySuccessor`: choose ready row for exact occurrence/folder and confirm detail readiness before binding; invalidated continuation review returns to occurrence context. |
| Failed global refresh left review decisions enabled | `failedGlobalRefreshBlocksAllReviewMutationsUntilRecovery`: central stale-state mutation gate plus disabled controls until successful authoritative refresh. |
| Identical registration failures could claim available | `repeatedSameFailureCannotReportAvailableUntilSuccessfulRegistration`: derive availability from registration readiness and retained failure, not only notification permission. |
| Foreground receipt and explicit refresh did not update runtime/inbox | `foregroundReceiptRefreshesInboxOnlyForCurrentSession`, `explicitSuccessfulRefreshAdvancesAuthoritativeDashboardEvenIfPayloadUnchanged`, `receiptDuringActiveRefreshQueuesAuthoritativeFollowup`: session-bound receipt triggers inbox refresh; authoritative dashboard revision triggers registration retry/reconciliation while STARTED. Receipt during busy refresh queues one read-only follow-up. |
| Resolved/replaced notifications never reconciled | `dashboardReconciliationRequiresExactFolderVersionAndReadyState`: authoritative reads reconcile feature notification identity/version/folder. Added device test `authoritativeReconciliationRemovesResolvedAndReplacedTargetsButKeepsUploads`, compiled but not executed. |
| Conflict read-back left handled inbox row | `conflictReadbackRefreshesHandledInboxWithoutReplay`: refresh dashboard after 409 read-back without replaying decision; failed inbox refresh retains stale state. |

Missing interfaces were observed RED before implementation. Historical-review,
global-stale, conflict-inbox and busy-receipt regressions also failed with runtime
assertions before their fixes. Complete post-fix Android suite passed 161/161,
with debug APK, lint and instrumentation compilation. Native notification/picker
side effects still require the dedicated-device checks above.

## Decisions and remaining limits

These record implementation rulings, including their cost if wrong:

1. Graph index resolves main checkout: inspect exact worktree source when coverage
   is insufficient. Cost: slower discovery, no behavior change.
2. Historical review existence needs `ReviewStore.has_for_occurrence`, not only
   pending lookup. Cost: one extra existence query per empty decision.
3. Reuse `ScheduleStore.emission_transaction` inside package lock for atomic
   schedule/audit updates. Cost: nested transaction requests are rejected; these
   endpoints run outside worker emission turns.
4. No device/AVD provisioning: compile runnable tests and explicitly leave native
   behavior unverified. Cost: device-specific failures can remain.
5. Reuse existing native VideoView composable for review preview. Cost: shared
   player regressions can affect conflict preview too.
6. Constrain existing transitive Fragment to Activity Result's required 1.3.0
   minimum, rather than suppress lint. Cost: transitive binary behavior changes.
7. Extract small internal `PushRegistration` for real HTTP rotation/retry/session
   tests without Firebase network hooks. Cost: one extra internal seam/file.
8. Rerun web serially after concurrent wait timeouts, without unrelated timeout or
   source edits. Cost: baseline nondeterminism remains documented.
9. Fresh reviewer inherited session model because tool contract forbids selecting
   another model without user's specific request. Cost: same-model-lineage bias,
   mitigated only by independent context.
10. Review declined real FCM/native/malformed-runtime certification: absent and
    synthetic config builds are not runtime proof. Cost: operator validation remains.
11. Full Activity history, completed browsing and offline caching stay non-goals.
    Cost: completed-package navigation awaits #37.
12. Baseline npm vulnerabilities/web timing/core skips remain documented, without
    unrelated dependency/toolchain changes. Cost: baseline risks remain for separate
    remediation.
13. Token-to-FID migration stays outside current server contract. Cost: later SDK
    migration needs coordinated server/client changes.
14. Retain this plan's ignored logs/ledger until device handoff rather than discard
    unexecuted-check evidence. Cost: ignored disk usage remains.

No deferred Minor review findings. Branch/worktree and ignored verification logs
remain available for operator/device handoff; nothing was pushed, merged or deployed.
