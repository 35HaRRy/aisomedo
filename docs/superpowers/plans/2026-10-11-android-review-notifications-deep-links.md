# Android Review, Notifications, and Deep Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution method must be chosen by the user before implementation.

**Goal:** Implement issue #36: exact Android review decisions, a durable approval inbox, actionable FCM notifications, and same-occurrence upload/render continuation.

**Architecture:** Reuse `DojoPublishing`, existing package locks/stores, the Android authenticated transport, and current session/upload runtime. Add narrowly guarded empty-occurrence decisions and reminders; Android owns presentation, not publication state. Dashboard pending actions supply the inbox without a second local database.

**Tech Stack:** Python/FastAPI/PostgreSQL, Kotlin/Compose Material 3, coroutines, OkHttp, native VideoView/date-time controls, Firebase Messaging, existing pytest/JUnit/MockWebServer/Android instrumentation.

**Spec:** `docs/superpowers/specs/2026-10-11-android-review-notifications-deep-links-design.md` (approved).

## Global Constraints

- Android 10 minimum: preserve `minSdk=29`, `compileSdk=35`, `targetSdk=35`, and existing four destinations.
- Use `Dojo Paylaşım Paketi`, `Dojo Yayın Planı`, `Yayın Zamanı`, and `Yayın İncelemesi`; externalize Turkish strings.
- `Europe/Istanbul`; strictly future reschedule; default reminders every 360 minutes, 08:00 inclusive–22:00 exclusive.
- No local approval database, offline command replay, separate push service, new delivery outbox, or general Activity/settings redesign.
- Notification shortcuts open app forms; never approve/skip/reschedule in a service or receiver.
- All authenticated media stays same-origin, private, bounded, and redirect-disabled. Credentials never enter URLs, saved state, payloads, or logs.
- Session generation/binding and 401/426 gates apply to every read, mutation, preview, token callback, and restored destination.
- No Firebase project creation, production push, deployment, or production mutation during automated verification.
- Live FCM delivery needs operator configuration and a device; synthetic tests cannot claim it passed.

## Review Focus

1. A slow response for review A arrives after review B opens: it must not replace B or authorize A's preview (Task 3).
2. A duplicate notification uses the same target but a different shortcut: pending intents must keep the correct form and never POST (Task 5).
3. An empty-package action races with media finalization/render: reject the old empty decision, keep the exact occurrence, and never create a fake review (Tasks 1 and 6).
4. Permission denied, no Google services, or malformed Firebase configuration: review/inbox remain usable and push availability is truthful (Task 5).
5. Preview download runs out of space or is cancelled after a session switch: delete only this feature's private partial file and leave Approve disabled (Task 4).

## File Map and Execution Notes

Existing files change in place; do not split/rewrite unrelated publishing or ViewModel code.

| Area | Files and responsibility |
| --- | --- |
| Occurrence decisions | `dojo-core/src/dojo/publishing.py`, `exceptions.py`, `__init__.py`; `backend/src/backend/routes/reviews.py`: guarded domain decisions and HTTP DTOs |
| Reminders | `dojo-core/src/dojo/publishing.py`, `model.py`, `adapters/fcm.py`: empty cadence and actionable data-message transport |
| Generated contract | `backend/scripts/generate_clients.py`, `backend/openapi.json`, `web/src/api/openapi.ts`, `android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt` |
| Android review state | New `android/app/src/main/java/com/dojo/aisomedo/reviews/ReviewState.kt`; existing `AppViewModel.kt`, `api/DojoApi.kt` |
| Review presentation | New `android/app/src/main/java/com/dojo/aisomedo/ui/ReviewScreen.kt`, `reviews/ReviewPreview.kt`; existing `ui/DojoApp.kt`, `ui/DashboardScreen.kt`, `res/values/strings.xml` |
| Push | New `android/app/src/main/java/com/dojo/aisomedo/notifications/NotificationTarget.kt`, `ReviewNotifications.kt`, `PushRuntime.kt`, `DojoMessagingService.kt` |
| Lifecycle/build | Existing `MainActivity.kt`, `AndroidManifest.xml`, Android Gradle files, `.gitignore`; new `res/drawable/ic_review.xml` |
| Evidence/setup | New `docs/verification/issue-36.md`: reproducible checks and operator Firebase/device steps |

Paths in task Files blocks are repo-relative. Android commands run from `android/`; on Windows use `./gradlew.bat`, on CI use `./gradlew`. Python commands run from repo root. Reuse CI's JDK 25 and existing SDK installation; do not upgrade unrelated dependencies.

Before execution, invoke using-git-worktrees, inspect existing worktrees/user changes, and establish the approved isolated workspace. Record baseline `git status --short`, Android unit/build checks, and affected Python checks. On Windows, save baseline contract with `Copy-Item backend/openapi.json "$env:LOCALAPPDATA/Temp/opencode/issue-36-base-openapi.json"` only after confirming that destination is not another session's artifact. Do not re-run brainstorming or rewrite this approved design unless a material incompatibility is discovered.

## Task 1: Guarded Empty-Occurrence Decisions and Contract

**Files:** Modify `dojo-core/src/dojo/publishing.py`, `dojo-core/src/dojo/exceptions.py`, `dojo-core/src/dojo/__init__.py`, `backend/src/backend/routes/reviews.py`, `backend/scripts/generate_clients.py`; regenerate the three contract artifacts above. Create `dojo-core/tests/test_empty_occurrence.py`; extend `backend/tests/test_focused_review_api.py` and `backend/tests/test_contract.py`.

**Interfaces:**
- Consume existing `ScheduleStore.list_due/list_all/update/create`, package lock, `SettingsStore`, and review store.
- Produce `DojoPublishing.skip_empty_occurrence(occurrence_id: int, expected_folder_name: str, *, confirmed: bool, requester: str | None = None) -> dict[str, object]`.
- Produce `DojoPublishing.reschedule_empty_occurrence(occurrence_id: int, expected_folder_name: str, new_due_at: datetime, *, requester: str | None = None) -> dict[str, object]`.
- Add `OccurrenceNotFound` and `OccurrenceChanged` domain exceptions; export through `dojo`.
- Add DTOs `EmptySkipIn(expected_folder_name: str, confirmed: bool = False)`, `EmptyRescheduleIn(expected_folder_name: str, new_due_at: datetime)`, and `OccurrenceDecisionOut(occurrence_id: int, package_folder: str, status: str, next_regular_at: datetime | None, oneoff_occurrence_id: int | None, new_due_at: datetime | None)`.
- Routes: `POST /api/reviews/occurrences/{occurrence_id}/skip` and `/reschedule`, returning `OccurrenceDecisionOut`. Invalid confirmation/time: 400; absent occurrence: 404; changed/resolved/nonempty context or publication in progress: 409; pairing/version gates unchanged.

- [ ] **Step 1: Add failing seam and HTTP tests.** Reuse existing `make_seam`, `FakeClock`, upload/render helpers, and `app(tmp_path, finalize=False)` patterns; keep new test setup local to this feature. Assert:

```python
# test_empty_skip_requires_confirmation_and_preserves_package
with pytest.raises(SkipRequiresConfirmation):
    seam.skip_empty_occurrence(occ.id, folder, confirmed=False)
result = seam.skip_empty_occurrence(occ.id, folder, confirmed=True, requester="9")
assert result["status"] == "skipped"
assert seam.get_active_package().folder_name == folder
assert seam.list_pending_reviews() == []
assert result["next_regular_at"] == next_regular.due_at

# test_empty_reschedule_preserves_plan_and_reuses_oneoff
assert result["status"] == "rescheduled"
assert result["new_due_at"] == future
assert seam.get_plan() == plan_before
assert len(pending_oneoffs) == 1

# test_late_empty_decision_rejects_finalized_or_reviewed_context
with pytest.raises(OccurrenceChanged):
    seam.skip_empty_occurrence(occ.id, folder, confirmed=True)
assert seam.list_pending_reviews() == reviews_before
```

Also add `test_empty_decisions_require_pairing_and_exact_folder`, `test_empty_decisions_reject_missing_resolved_future_and_replaced_context`, and `test_empty_reschedule_rejects_now_and_past_without_writes`. HTTP assertions pin 401/400/404/409 and no changed schedule on failure. Add a real `pg_store` concurrency test: two threads/seams share store/root, race skip versus reschedule, exactly one succeeds; race finalization before the empty decision and assert conflict. No sleeps to manufacture the winner.

- [ ] **Step 2: Run red checks.** `uv run --project dojo-core pytest dojo-core/tests/test_empty_occurrence.py -v`; `uv run --project backend pytest backend/tests/test_focused_review_api.py -v`. New tests fail because methods/routes do not exist, not because test infrastructure is broken.
- [ ] **Step 3: Implement the interfaces.** Validate under existing package/store transaction boundary: exact active folder, due pending occurrence, no existing review for that occurrence, and no finalized usable media. Do not infer occurrence-to-package ownership from a nonexistent DB field: compare the locked current dashboard/package context. Resolve skip and audit `occurrence.skipped`; reschedule regular/manual by resolving it and creating one pending one-off, or move an existing one-off's due time. Audit `occurrence.rescheduled`; leave regular cadence/package unchanged. Reuse `SkipRequiresConfirmation`, `RescheduleTimeInvalid`, and publication-in-progress guard. Add the new consumed Kotlin DTO roots plus `ReviewDetailOut`, `ApproveIn`, `SkipIn`, `RescheduleIn`, `RenderIn`, `RenderOut`, and `PushTokenIn` to generation; use existing JSON responses for old review action results rather than changing their public shape.
- [ ] **Step 4: Run green/contract checks.** Run Step 2 commands; run `uv run --project backend python backend/scripts/export_openapi.py`, then `uv run --project backend python backend/scripts/generate_clients.py`, then `uv run --project backend pytest backend/tests/test_contract.py -v`. New tests and existing focused review tests pass. Generate a second time and confirm identical output; run `uv run --project backend python backend/scripts/check_openapi_compat.py "$env:LOCALAPPDATA/Temp/opencode/issue-36-base-openapi.json" backend/openapi.json` (no breaking change).
- [ ] **Step 5: Commit only Task 1 files.** Message: `feat(review): resolve empty occurrences safely`.

## Task 2: Empty Reminders and Actionable FCM Message Shape

**Files:** Modify `dojo-core/src/dojo/publishing.py`, `dojo-core/src/dojo/model.py`, `dojo-core/src/dojo/adapters/fcm.py`, `dojo-core/tests/test_fcm.py`; create `dojo-core/tests/test_empty_reminders.py`. Extend `dojo-core/tests/test_empty_occurrence.py` for reminder stop behavior; reuse `test_publication.py` outcome coverage.

**Interfaces:**
- Preserve `send_due_reminders() -> None` and `FcmNotifier.send(notification: Notification, tokens: list[str]) -> NotificationResult`.
- Persist one compact map under settings key `reminders.empty_occurrences`: occurrence ID string → `{package_folder: str, last_reminded_at: ISO datetime string}`. This is cadence metadata, not an inbox.
- Empty data: `type=empty_package`, `occurrence_id`, `package_folder`; review data remains `type=review_required`, `review_id`, `review_version`, `package_folder`.
- For review/empty types, adapter emits data-only messages with `title`, `body`, and `AndroidConfig(priority="high")`. Outcome/monitoring message shapes remain mixed notification/data.

- [ ] **Step 1: Add failing behavior tests.** Use fake clock, registered paired devices, stub notifier, and genuine Firebase message types via existing `FakeSender`. Assert:

```python
# test_empty_reminder_is_durable_and_honors_quiet_window
assert sent.data["type"] == "empty_package"
assert sent.data["occurrence_id"] == str(occ.id)
assert sent.data["package_folder"] == folder
assert deliveries_after_restart_before_360_minutes == deliveries_before_restart
assert deliveries_at_07_59 == 0
assert deliveries_at_08_00 == 1
assert deliveries_at_22_00 == deliveries_before_22_00

# test_review_and_empty_messages_are_actionable_data_only
assert message.notification is None
assert message.android.priority == "high"
assert message.data["title"] == notification.title
assert message.data["body"] == notification.body
```

Add tests for no registered devices, whole-call failure leaving cadence unchanged, invalid token removal, corrupt cadence entries, multiple due occurrences, pruning after upload/finalization or resolution, and next eligible review reminder after render. Pin publication outcome and operational alert `message.notification` presence. Replace the existing review test expecting `android is None`, not the operational tag test.

- [ ] **Step 2: Run red check.** `uv run --project dojo-core pytest dojo-core/tests/test_empty_reminders.py dojo-core/tests/test_fcm.py -v`. Only new/changed assertions fail.
- [ ] **Step 3: Extend existing reminder turn.** Calculate both pending review and empty occurrence eligibility before returning early; current `if not pending: return` must not suppress empty work. Reuse policy/window, active registrations, package lock, batch failure handling, and externalized model constants for empty title/body. Prune metadata even when there are no recipients; never advance a new target's cadence without a completed dispatch. Keep existing completed-batch retry semantics. Branch Firebase payload only for the two actionable types; normalize all data values to strings.
- [ ] **Step 4: Run green and compatibility regressions.** Run Step 2 plus `uv run --project dojo-core pytest dojo-core/tests/test_empty_occurrence.py dojo-core/tests/test_publication.py dojo-core/tests/test_monitoring_delivery.py -v`. Repeat cadence persistence with real `pg_store` settings across a newly constructed seam; all checks pass without live Firebase.
- [ ] **Step 5: Commit Task 2 files.** Message: `feat(push): notify empty packages with actions`.

## Task 3: Android Review API and Session-Safe State

**Files:** Modify `android/app/src/main/java/com/dojo/aisomedo/api/DojoApi.kt`, `android/app/src/main/java/com/dojo/aisomedo/AppViewModel.kt`, `android/app/src/test/java/com/dojo/aisomedo/api/DojoApiTest.kt`, `android/app/src/test/java/com/dojo/aisomedo/AppViewModelTest.kt`. Create `android/app/src/main/java/com/dojo/aisomedo/reviews/ReviewState.kt` and `android/app/src/test/java/com/dojo/aisomedo/reviews/ReviewStateTest.kt`.

**Interfaces:**
- `DojoApi.review(id: Int): ReviewDetailOut`, `approveReview(id: Int, version: Int): JsonObject`, `skipReview(id: Int, version: Int): JsonObject`, `rescheduleReview(id: Int, version: Int, newDueAt: String): JsonObject` (all suspend).
- Suspend `skipEmptyOccurrence(id: Int, body: EmptySkipIn): OccurrenceDecisionOut`, `rescheduleEmptyOccurrence(id: Int, body: EmptyRescheduleIn): OccurrenceDecisionOut`, `renderPackage(folder: String, retry: Boolean = false): RenderOut`, `registerPushToken(token: String): Unit`, `removePushToken(): Unit`.
- `enum class ReviewAction { REVIEW, UPLOAD, SKIP, RESCHEDULE }`.
- `data class ReviewTarget(val reviewId: Int? = null, val occurrenceId: Int? = null, val packageFolder: String? = null, val expectedVersion: Int? = null, val action: ReviewAction = ReviewAction.REVIEW)`; a valid target has exactly one positive ID. Review targets opened by ID alone bind the fetched identity; notification targets require expected folder/version.
- `enum class ReviewIssue { NETWORK, INVALID_TIME, INVALID_RESPONSE, STALE, ALREADY_HANDLED, NOT_FOUND, UNCERTAIN, PREVIEW, RENDER_FAILED, PACKAGE_CHANGED }`.
- `data class ReviewState(val target: ReviewTarget? = null, val detail: ReviewDetailOut? = null, val busy: Boolean = false, val readRequired: Boolean = true, val previewReady: Boolean = false, val issue: ReviewIssue? = null, val continuing: Boolean = false, val nextRegularAt: String? = null, val publication: JsonObject? = null)`; computed `canApprove: Boolean` requires pending, render-ready, exact prepared preview, and no busy/read-required/issue state.
- Pure `futureIstanbulInstant(date: LocalDate, time: LocalTime, now: Instant): String?` returns an offset-aware ISO instant only when strictly future.
- Add `AppUiState.review: ReviewState`, `openReview(target: ReviewTarget)`, `refreshReview()`, `requestReviewAction(action: ReviewAction)`, `approveReview()`, `skipReview()`, `rescheduleReview(date: LocalDate, time: LocalTime)`, `closeReview()`, `markReviewPreviewReady(id: Int, revision: String, ready: Boolean)` to the model. All non-suspend except the preview download introduced in Task 4.

- [ ] **Step 1: Add failing API/state tests.** Extend current MockWebServer dispatcher/fixture rather than introducing another framework. Record requests and assert:

```kotlin
// reviewActionsUseDisplayedIdentityAndExplicitBodies
assertEquals("/api/reviews/7/approve", request.path)
assertEquals("{\"version\":3}", request.body.readUtf8())
assertEquals("Bearer DEVICE", request.getHeader("Authorization"))
assertEquals("1", request.getHeader("X-Android-Version-Code"))
assertTrue(skipBody["confirmed"]!!.jsonPrimitive.boolean)

// onlyPreparedCurrentPendingPreviewCanApprove
assertFalse(unprepared.canApprove)
assertFalse(stale.canApprove)
assertFalse(resolved.canApprove)
assertTrue(prepared.canApprove)

// rescheduleUsesIstanbulAndRejectsNow
assertNull(futureIstanbulInstant(date, time, exactInstant))
assertEquals("+03:00", OffsetDateTime.parse(future!!).offset.toString())
```

Add VM tests for 409 handled/stale distinctions, 404, 401, 426, double-tap one POST, ambiguous response requiring read-back, cancelled requests, and old-server/old-target delayed responses. Add `preparedPreviewSurvivesSameRevisionRefresh`: `assertTrue(model.state.value.review.canApprove)` after a successful unchanged detail refresh, but `assertFalse(...)` if revision/readiness changes. Verify a newly constructed model reloads the same durable dashboard inbox and saved target but never submits. Explicitly pin Review Focus #1.

- [ ] **Step 2: Run red check.** `./gradlew.bat :app:testDebugUnitTest --tests "com.dojo.aisomedo.reviews.ReviewStateTest" --tests "com.dojo.aisomedo.AppViewModelTest" --tests "com.dojo.aisomedo.api.DojoApiTest"`. Expected new missing APIs/state assertions fail; baseline tests still pass once compilation reaches them.
- [ ] **Step 3: Implement transport and state.** Reuse generated DTOs and `request`/`bytes`; no action-response SDK rewrite. Give approval a bounded 120-second call/read timeout because backend publication is synchronous; retain default 30-second call timeout elsewhere and no automatic replay. Gate model work with both session generation and captured target identity. Save target scalar keys plus origin/binding and owning destination; clear through existing session reset. Fetch dashboard for inbox/empty context and exact detail for a review; do not fetch pending reviews redundantly. On conflict or uncertain response, require fresh read before another mutation. Never interpret every 409 as already handled without refreshed detail.
- [ ] **Step 4: Run green checks.** Run Step 2, then `./gradlew.bat :app:testDebugUnitTest`. All existing onboarding/upload/editor tests and new review tests pass. Verify no mutation is made by target restoration or `requestReviewAction`.
- [ ] **Step 5: Commit Task 3 files.** Message: `feat(android): add guarded review decisions`.

## Task 4: Exact Native Preview, Review Forms, and Inbox UI

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/ui/ReviewScreen.kt`, `android/app/src/main/java/com/dojo/aisomedo/reviews/ReviewPreview.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/ui/ReviewScreenTest.kt`, `android/app/src/androidTest/java/com/dojo/aisomedo/reviews/ReviewPreviewTest.kt`. Modify `ui/DojoApp.kt`, `ui/DashboardScreen.kt`, `AppViewModel.kt`, `api/DojoApi.kt`, `res/values/strings.xml`, and existing `ui/DojoAppTest.kt` under their current Android source sets.

**Interfaces:**
- Suspend `DojoApi.downloadReviewPreview(path: String, destination: File, limit: Long = 512L * 1024 * 1024): Unit`, reusing existing streamed `bytes` destination support.
- Suspend `AppViewModel.downloadReviewPreview(id: Int, revision: String, destination: File): Unit`: require current target/detail/session identity before and after transfer; delete partial file on rejection.
- `@Composable ReviewPreview(detail: ReviewDetailOut, onDownload: suspend (Int, String, File) -> Unit, onReady: (Int, String, Boolean) -> Unit)` owns only its `review-previews/` cache file and native VideoView lifecycle.
- `@Composable ReviewScreen(state: ReviewState, enabled: Boolean, onAction: (ReviewAction) -> Unit, onApprove: () -> Unit, onSkip: () -> Unit, onReschedule: (LocalDate, LocalTime) -> Unit, onRefresh: () -> Unit, onClose: () -> Unit, preview: @Composable (ReviewDetailOut) -> Unit)`; preview slot is for production player and deterministic screen tests, not a new service abstraction.
- Extend Dashboard callback `onPending: (DashboardActionOut, ReviewAction) -> Unit`; reuse pending-row rendering for Activity's inbox and known next occurrence via existing `formattedTime`.

- [ ] **Step 1: Add failing UI/preview tests.** With synthetic detail and callback counters, assert:

```kotlin
// exactCaptionAndConfirmationAreVisible
compose.onNodeWithText("Exact caption\n#dojo").assertIsDisplayed()
compose.onNodeWithTag("review-approve").assertIsNotEnabled()
compose.onNodeWithTag("review-skip").performClick()
assertEquals(0, skipCalls) // opening form is not confirmation
compose.onNodeWithTag("review-confirm-skip").performClick()
assertEquals(1, skipCalls)

// authenticatedPreviewRejectsRedirectAndClearsPartialFile
assertEquals("Bearer DEVICE", previewRequest.getHeader("Authorization"))
assertFalse(destination.exists())
assertFalse(model.state.value.review.canApprove)
```

Add assertions for literal caption display, player preparation/error, 512 MiB streaming bound without allocating that amount (use a reduced limit in transport test), cancellation/session switch, insufficient disk simulation at file-write seam, native reschedule cancellation and future validation, Back returning to owner, Activity inbox unavailable versus genuinely empty, and phone/tablet navigation. Use existing device fixture/media-fixture patterns; never use user media.

- [ ] **Step 2: Run red checks.** `./gradlew.bat :app:assembleDebugAndroidTest` fails on missing screen/player interfaces. With emulator/device available, `./gradlew.bat :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.ReviewScreenTest,com.dojo.aisomedo.reviews.ReviewPreviewTest` runs new assertions red.
- [ ] **Step 3: Implement UI/player.** Stream the exact authenticated review URL into app-private cache; native playback consumes the local file, not a Bearer URL. `onPrepared` marks only matching ID/revision ready; `onError`, changed revision, closed flow, and disposal revoke readiness and remove its file. Add accessible player controls and no autoplay publication. Show caption/status, separate loading/handled/stale/error states, skip confirmation with next regular time, and native date/time dialogs labelled Istanbul. Wire focused flow above four destinations; show actionable dashboard rows and Activity approval inbox. Persist non-secret form/navigation inputs, never submitted commands. Add lifecycle-owned 5-second polling only while pending review/continuation is visible; cancel when stopped/closed and avoid overwriting form drafts or overlapping reads.
- [ ] **Step 4: Run green checks.** Run Step 2 where hardware permits; also `./gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest`. Compile/lint/unit success is not reported as instrumentation execution. No external player/browser receives credentials.
- [ ] **Step 5: Commit Task 4 files.** Message: `feat(android): show exact review and approval inbox`.

## Task 5: FCM Runtime, Permission, and Cold/Warm Deep Links

**Files:** Create `android/app/src/main/java/com/dojo/aisomedo/notifications/NotificationTarget.kt`, `ReviewNotifications.kt`, `PushRuntime.kt`, `DojoMessagingService.kt`, `android/app/src/main/res/drawable/ic_review.xml`, `android/app/src/test/java/com/dojo/aisomedo/notifications/NotificationTargetTest.kt`, and `android/app/src/androidTest/java/com/dojo/aisomedo/notifications/ReviewNotificationsTest.kt`. Modify `MainActivity.kt`, `AppViewModel.kt`, `ui/DojoApp.kt`, `res/values/strings.xml`, `AndroidManifest.xml`, `android/build.gradle.kts`, `android/app/build.gradle.kts`, `.gitignore`; extend API/VM tests from Task 3.

**Interfaces:**
- `data class NotificationTarget(val type: String, val packageFolder: String, val reviewId: Int? = null, val reviewVersion: Int? = null, val occurrenceId: Int? = null, val action: ReviewAction = ReviewAction.REVIEW)`.
- Pure `parseNotificationTarget(data: Map<String, String>): NotificationTarget?`: types `review_required`, `empty_package`, `publication_confirmed`, `publication_failed` only; positive Int IDs/version; folder length 1–128, nonblank, no `/`, backslash, ISO control characters, or exact `.`/`..`; `action` must exactly match an allowed uppercase `ReviewAction` name. Review allows REVIEW/SKIP/RESCHEDULE; empty allows UPLOAD/SKIP/RESCHEDULE. Default review action REVIEW, empty action UPLOAD; publication outcomes route to Activity context without mutation shortcuts.
- `ReviewNotifications(context: Context).show(target: NotificationTarget, title: String, body: String, bindingId: String): Unit`, `cancelReview(id: Int): Unit`, `cancelOccurrence(id: Int): Unit`, `clear(): Unit`. Channel `dojo-reviews`; stable tags `review:<id>`/`occurrence:<id>`; separate outcome display channel `dojo-publications` for SDK mixed messages.
- `PushRuntime.get(context: Context): PushRuntime`, `refresh(token: String? = null): Unit`, `receive(data: Map<String, String>): Unit`, `stopSession(): Unit`; retain only application context and existing `SessionStore`. Expose `StateFlow<PushAvailability>` and `StateFlow<PushFailure?>`.
- `enum class PushAvailability { UNCONFIGURED, SERVICES_UNAVAILABLE, PERMISSION_DENIED, AVAILABLE, REGISTRATION_FAILED }`; `data class PushFailure(val origin: String, val bindingId: String, val status: Int, val updateUrl: String? = null)`.
- `AppViewModel.openNotification(target: NotificationTarget, origin: String, bindingId: String): Unit` queues non-secret target until READY and routes through Task 3. `observePushFailure(failure: PushFailure): Unit` applies existing auth/version handling only for matching current origin/binding.

- [ ] **Step 1: Add failing parser, notification, and lifecycle tests.** Assert:

```kotlin
// unknownOrMalformedPayloadCannotRoute
assertNull(parseNotificationTarget(mapOf("type" to "approve", "review_id" to "7")))
assertNull(parseNotificationTarget(reviewData + ("review_id" to "2147483648")))
assertNull(parseNotificationTarget(reviewData + ("action" to "approve")))

// shortcutsAreImmutableExplicitAndDistinct
if (Build.VERSION.SDK_INT >= 31) {
    assertTrue(reviewIntent.isImmutable)
    assertTrue(skipIntent.isImmutable)
}
assertNotEquals(reviewIntent, skipIntent)
assertEquals("SKIP", launchedIntent.getStringExtra("action"))
assertEquals(0, recordedMutationRequests)
```

Test duplicate payload replaces same notification; shortcuts keep distinct target/action identities; malformed paths/control characters are rejected; 401/426 registration failures cannot revoke a newer session; token rotation sends only to captured current origin; denied notification permission does not hide inbox. Instrument cold start, `onNewIntent`, process recreation with pending pairing, and outcome launcher extras. Verify stale folder/version opens an explanation, never a newer review.

- [ ] **Step 2: Run red checks.** `./gradlew.bat :app:testDebugUnitTest --tests "com.dojo.aisomedo.notifications.NotificationTargetTest"`; instrumentation compilation and available `ReviewNotificationsTest` execution fail on missing interfaces.
- [ ] **Step 3: Implement configured and unconfigured paths.** Pin Google services plugin `4.5.0` (official setup docs) and Firebase BoM `34.19.0` (Context7 docs); add only main `firebase-messaging` module, no KTX/Analytics. Apply Google services plugin only when operator-provided `android/app/google-services.json` exists; ignore that file in git. Guard missing default Firebase app and unsupported Google services; normal debug/CI builds remain possible without real configuration. Use current registration token API plus `onNewToken` because existing server addresses tokens; do not migrate server to Firebase installation IDs. Never copy docs' token logging examples.

Declare non-exported messaging service and default outcome channel/icon metadata. Disable messaging auto-init in manifest until configured, paired runtime enables it; synthetic/unpaired test startup must not contact Firebase. Create channels before registration so background mixed outcomes use correct settings. Request Android 13+ permission through existing Activity Result conventions, with denied/settings state visible. `onMessageReceived` synchronously parses and renders visible notifications without a network fetch; token callback syncs captured current session and retries next active refresh on failure. Deduplicate successful `(origin,binding,token)` registration in memory and retry failed registration; no new background queue. Use explicit immutable intents whose identity includes target and action. Tag/ID namespaces must not collide with upload notifications.

MainActivity handles initial intent and `onNewIntent` (including `setIntent`) through the same validation path, while preserving existing PACKAGE upload intents. Route mixed publication outcomes to refreshed Activity with named package context. Observe push failures with origin/binding guards. On session stop, cancel local notifications/queued targets; make previous-registration removal bounded best effort before old credentials are discarded, never block a server change on network failure. No remote command executes until user presses a form control.

- [ ] **Step 4: Run green checks.** Run Step 2 plus full Android unit/build/lint/instrumentation compilation. Execute notifications instrumentation when a device exists. Test both absent config and synthetic Firebase JSON without overwriting any real config: isolate fixture in worktree, clean up only the file created by this test, and never fetch a real token. Test SDK initialization errors with local resource/test doubles, not live endpoints.
- [ ] **Step 5: Commit Task 5 files.** Message: `feat(android): add FCM review deep links`.

## Task 6: Same-Occurrence Upload → Render → Review

**Files:** Modify `AppViewModel.kt`, `MainActivity.kt`, `ui/DojoApp.kt`, `ui/ReviewScreen.kt`, `reviews/ReviewState.kt`, and `res/values/strings.xml` in Android main sources. Extend `AppViewModelTest.kt`, `ui/ReviewScreenTest.kt`, and `backend/tests/test_focused_review_api.py`; create `android/app/src/androidTest/java/com/dojo/aisomedo/reviews/ReviewContinuationTest.kt`.

**Interfaces:**
- `AppViewModel.continueReview(uploadRows: List<UploadRecord>, retry: Boolean = false): Unit` consumes Task 3's bound empty target and existing upload rows. Only matching current-session rows affect readiness; unresolved upload/conflict/failure blocks explicit continuation.
- `ReviewState.continuing` tracks explicit waiting; worker-driven render/review appearing first is valid. Use existing `refreshReview()`/dashboard to find exact `occurrence_id` and `package_folder`, then bind its returned review ID/version; never choose `first()` from an unrelated pending list.
- Add `@Composable ReviewContinuation(state: ReviewState, enabled: Boolean, uploadRows: List<UploadRecord>, onContinue: (List<UploadRecord>, Boolean) -> Unit, onAction: (ReviewAction) -> Unit, onRefresh: () -> Unit, onClose: () -> Unit)` in existing `ReviewScreen.kt`. Show it above existing Package editor/upload panel while target action is UPLOAD; do not leave a focused overlay covering the picker/editor.
- Banner's continuation action passes current runtime rows; it calls existing upload picker and render API, not `manual_publish`. Preserve owning destination so cancelling the flow returns there.

- [ ] **Step 1: Add failing continuation tests.** Reuse existing upload fixtures and backend same-occurrence test. Assert:

```kotlin
// waitingUploadOrConflictCannotTriggerRender
assertEquals(0, renderPostsWhileQueued)
assertEquals(0, renderPostsWhileConflict)

// finalizedUploadContinuesExactOccurrenceOnce
assertEquals("active", renderBody["expected_folder_name"]!!.jsonPrimitive.content)
assertEquals(1, renderPosts)
assertEquals(7, model.state.value.review.target!!.reviewId)
assertEquals(originalOccurrenceId, model.state.value.review.detail!!.review.occurrenceId)
assertTrue(requests.none { it.path == "/api/packages/active/manual-publish" })
```

Add tests for foreign-session upload rows, render already completed by worker, failure/explicit retry, original occurrence skipped elsewhere, package replaced between tap and response, no network/render on rotation, and stop polling on Back/background. Backend test continues existing real upload/finalization/render sequence and asserts one active package and no duplicate occurrence.

- [ ] **Step 2: Run red checks.** `./gradlew.bat :app:testDebugUnitTest --tests "com.dojo.aisomedo.AppViewModelTest"`; compile/run available `ReviewContinuationTest` instrumentation. New continuation tests fail without changing existing upload behavior.
- [ ] **Step 3: Connect existing runtime.** Preserve target across upload/conflict navigation. Refresh dashboard/editor before render; require current folder, due unresolved occurrence, finalized eligible media, and resolved local upload work. Existing MainActivity upload transitions already trigger refresh: extend that connection rather than add another uploader. Request one explicit expected-folder render, then poll with Task 4's lifecycle mechanism. Transition when exact occurrence's review is ready; stop/cancel on replacement, resolution, auth/version failure, or closed flow. Permit worker-first completion without redundant render. Empty Skip/Reschedule use Task 1 routes/forms and stop continuation immediately after success.
- [ ] **Step 4: Run green checks.** Run Step 2, full Android unit tests, and `uv run --project backend pytest backend/tests/test_focused_review_api.py -v`. Run continuation instrumentation when possible; no manual schedule mutation or extra active package is observed.
- [ ] **Step 5: Commit Task 6 files.** Message: `feat(android): continue empty packages to review`.

## Task 7: Integrated Verification and Setup Evidence

**Files:** Create `docs/verification/issue-36.md`; update `.github/workflows/ci.yml` only if a new check is not already covered by existing Android/backend/contract jobs. Existing jobs already run all relevant tests and instrumentation compilation; avoid duplicate jobs or Firebase credentials in PR CI.

**Interfaces:** Consumes Tasks 1–6. Produces reproducible automated evidence, explicit skipped checks, and operator setup/delivery checklist; does not deploy or send production pushes.

- [ ] **Step 1: Validate acceptance mapping against tests.** Each issue checkbox maps to named tests: exact deep link (Task 5), decisions/stale/inbox (Tasks 1/3/4), review/outcome sender and receiver (Tasks 2/5), empty continuation (Task 6). Add a focused missing assertion to its owning existing test if mapping is incomplete; demonstrate red before any fix. Do not add another framework or whole-stack harness.
- [ ] **Step 2: Run complete affected checks.** From repo root, run separately:

```text
uv run --project dojo-core pytest dojo-core/tests -v
uv run --project backend pytest backend/tests -v
uv run --project worker pytest worker/tests -v
uv run --project dojo-core ruff check dojo-core/src dojo-core/tests
uv run --project backend ruff check backend/src backend/tests backend/scripts
uv run --project dojo-core mypy dojo-core/src/dojo
uv run --project backend mypy backend/src/backend
uv run --project backend python backend/scripts/export_openapi.py
uv run --project backend python backend/scripts/generate_clients.py
```

From Android: `./gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest`, then `./gradlew.bat :app:connectedDebugAndroidTest` if emulator/device available. From web: `npm test`, `npm run build` because its generated contract changed. Confirm no generated drift after regeneration against committed artifacts and no breaking baseline OpenAPI changes. Docker/PostgreSQL/FFmpeg requirements and actual skipped tests must be reported, not bypassed.

- [ ] **Step 3: Write evidence and operator steps.** Include commands, actual counts/results, hardware/config limitations, and how to provide `google-services.json` for `com.dojo.aisomedo` matching backend `FCM_PROJECT_ID`/credentials. Explain config identifiers are not service-account secrets, but remain untracked by project convention. Release builder must provide the same file; no secret should enter source. Document permission, Google Play services, quiet-hour/cadence behavior, and inbox fallback. Provide foreground/background/cold-start checks for review-required, empty, publication success/failure; late other-device action; and same-package upload/render. Do not execute live pushes without user authorization.
- [ ] **Step 4: Review final diff and evidence.** Run `git diff --check`, verify only scoped files changed and no credentials/real config/private artifacts were added. Use required completion review workflow; if Native chosen, one fresh whole-branch reviewer follows inline implementation. Fix material findings with focused red/green regression checks. Do not claim acceptance for unexecuted device/FCM checks.
- [ ] **Step 5: Commit verification document and finish handoff.** Message: `docs(android): record issue 36 verification`. Report implementation outcome, test evidence, and remaining Firebase/device setup. Do not merge, push, close #36, or deploy unless authorized.

## Plan Self-Review and Handoff

- Spec coverage: Tasks 1–2 fill backend gaps; 3–4 cover exact review, durable inbox, stale/unsafe actions, and lifecycle; 5 covers configured push and validated deep links; 6 preserves continuation identity; 7 records automated versus live evidence.
- Type/name consistency: generated occurrence DTOs come from Task 1, review state/action types from Task 3, notification types/runtime from Task 5; later tasks consume these names directly.
- Review Focus: each of the five failure classes is pinned in its owning task's tests.
- Proportion: bodies remain implementation decisions; this plan specifies interfaces, assertions, and checkable steps, not a parallel implementation.
- Execution pending: user must review this plan and choose Native or Subagent-driven. Recommend Native because tasks share review/session interfaces and existing fixtures; it avoids repeated context while retaining final independent review.

## Documentation Sources Consulted

- Context7 `/websites/firebase_google`: Android BoM dependency setup and registration-token lifecycle (`getToken`/`onNewToken` remain the legacy-token path consumed by current backend; do not add token logging).
- `https://firebase.google.com/docs/android/setup`: Google services Gradle plugin `4.5.0`; pin compatible BoM `34.19.0` rather than introduce an unrelated major SDK migration.
- `https://firebase.google.com/docs/cloud-messaging/customize-messages/set-message-type`: foreground data receipt versus background notification/data launcher extras; custom review shortcuts require client-rendered data messages.
