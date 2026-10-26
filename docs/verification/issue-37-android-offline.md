# Issue #37 — Android offline cache and update prompt

## Development integration follow-up — 2026-10-13

The historical results below describe detached commit `2fdc498`, not the original
`development` HEAD `26f3c44`. That HEAD contained only the #37 design/plan and
untracked feature files; it did not wire the feature into the application. Its
Android unit-test build failed on missing Activity DTOs and offline resources.

The user approved adapting the existing implementation onto development while
preserving the subsequently integrated #36 review, continuation, and notification
features. No commit, push, release, or issue closure is authorized by this work.
The old branch must not replace current files wholesale: it predates #36.

Current host evidence:

- Final Android unit suite: **216 tests, 0 failures/errors/skips** after review fixes.
- Full backend suite: **210 passed**, one existing Starlette/httpx deprecation warning.
- Generator suite: **9 passed**; generator/test files pass Ruff. Two regenerations
  keep Android DTO, web DTO, and backend OpenAPI hashes unchanged.
- `assembleDebug`, `assembleDebugAndroidTest`, and `lintDebug` succeed; lint/compiler
  dependency/deprecation notices are not claimed resolved.
- Two new review regressions failed first, then passed:
  `immediateDisconnectBlocksReviewDecisionBeforeCollectorRuns` and
  `reconnectRequiresFreshReviewAndPreviewBeforeApproval`. They exercise real model,
  session storage, connectivity input, and HTTP transport. Review decisions now
  consume the shared live gate; network changes invalidate preview readiness and
  epoch-fence review reads. Existing #36 tests remain in the full suite.
- Preserved #36 review/continuation screens, exact-package upload callbacks,
  notifications/push settings, and Activity approval inbox. Recent history appears
  alongside that inbox rather than replacing it. Cached review detail/media is not
  added; offline package/history metadata and pending summaries remain readable.
- An initial 120-second suite/build command timed out after exposing a review-test
  race around asynchronous credential deletion. The subsequent complete suite
  passed; the test now waits for both global and review idle. The final combined
  unit/build/lint/instrumentation-build command passed after all product changes.

Device evidence: `connectedDebugAndroidTest` fails with
`DeviceException: No connected devices!`; `adb devices -l` and
`emulator -list-avds` return no devices/AVDs. Instrumentation builds do **not** prove
native callback, UIDT/WorkManager wake, Compose UI, or process-death behavior.
Keep #37 open pending the device matrix. Historical results below apply only to
the old detached implementation, not this integration.

### Independent integration review and fix pass

One read-only reviewer found no Critical issues, three Important issues, and an
open-picker read-only UX defect. All entered one targeted fix pass; no second
review or full device acceptance is claimed.

| Finding | Fix | Evidence |
| --- | --- | --- |
| Unknown-ID initialization can replay after disconnect/process death | Persist uncertain creation before POST; do not automatically create again without an acknowledged ID. Explicit online retry remains necessary for uncertain creation. Retain an ID delivered after connectivity loss. | Two replay regressions failed first, then passed. Complete UploadEngineTest passes, including before-send cancellation, write-ahead cancellation, restart, and acknowledged-ID boundaries. |
| FCM registration bypasses offline/update gate; background 426 only in memory | Registration and cleanup consult application-owned connectivity/version access; delivered rejection is persisted under identity fencing before signaling; shared runtime stops transfers/invalidates credentials without an Activity. | Offline-access and durable-426 regressions failed first, then passed; full PushRegistrationTest passes. Native runtime 401/426 integration scenario compiled, not executed. |
| Network startup sample precedes callback registration | Register first; any initial loss callback fences obsolete sampled connectivity. | Initial-loss regression failed first, then passed; complete NetworkMonitorTest passes. Real platform timing remains device-unverified. |
| Open review date/time dialog edits after authority disappears | Confirmation callbacks and reschedule submission check current access. | Two Compose regressions compile; not executed without devices. |

Final command: `./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest --console=plain`
exited 0. XML totals: **216 tests, 0 failures, 0 errors, 0 skipped**. Final backend
rerun: **210 passed**, one existing warning. `git diff --check` passes with repository
line-ending configuration; overriding `core.autocrlf=false` produced CRLF false
positives and is not the repository check. Backend OpenAPI and web DTO diff is empty.

### Integration decisions and remaining limits

- Reuse and adapt the existing #37 implementation, not replace #36 files wholesale;
  full regression suites guard adaptation risk. Existing untracked files are retained.
- API/upload/UI edits used disjoint ownership and fixed interfaces; only parent
  ran Android Gradle. Compiler/full-suite checks guard interface mismatch.
- The historical spec's absent-review assumption is obsolete. Existing #36 actions,
  fresh exact-review reads, and preview readiness now participate in the shared gate.
- Asynchronous credential deletion can expose a busy pairing state; tests wait for
  completed durable deletion rather than treating that intermediate state as final.
- Open-picker protection is required read-only UX, not deferred polish. Actual
  dialog interaction remains unverified until device execution.
- Keep best-effort old push-token removal when connected and version-supported;
  current identity checks still protect registration. Device/backend cleanup needs proof.
- Process definitive FCM 401/426 even after access loss, under captured-identity
  checks; cache failure must not suppress runtime shutdown. Native callback proof is pending.
- Unknown upload creation cannot be reconciled without an ID/idempotency key.
  Require explicit retry rather than silently replaying POST; an unacknowledged
  server-side record may remain until expiry. Known-ID progress still resumes normally.
- Dedicated-device handover, both schedulers, background/process death, Compose,
  accessibility, and signed APK installation remain unaccepted. No production
  dependency, backend endpoint, offline command queue, release, or signing change added.

No deferred product findings from this review; device-only fixes are host/build
verified only. Keep issue #37 open until device acceptance is evidenced.

Date: 2026-10-12. Execution: Native in isolated OpenCode worktree.
Product review range starts at `1a11eb1`; no merge, push, release, or issue closure.
Product fixes after review are committed at `f92249c`; host run on that content
has 147 passing Android unit tests, both debug APK builds, and successful lint.

## Verdict

Host implementation checks pass. **Device acceptance is blocked**:
`connectedDebugAndroidTest` fails with `DeviceException: No connected devices!`.
`adb devices -l` reports no attached devices. Instrumentation assembly is not
evidence of executed Compose UI, native callback, or background scheduler behavior.
Keep #37 open until the dedicated-device matrix below has evidence.

## Host evidence

- Android unit suite: **147 tests, 0 failures, 0 errors** after review fixes.
- Full backend suite: **207 passed**, one existing Starlette/httpx deprecation warning.
- Client-generator suite: **9 passed**; generator and regression tests pass Ruff.
- Debug APK, instrumentation APK, and lint build successfully. Lint suggestions
  remain, including existing dependency/SDK and UI/resource notices; no lint errors.
- Regeneration leaves committed Android DTOs, web DTOs, and backend OpenAPI unchanged.
- `git diff --check` passes. No product dependency or backend endpoint was added.
- Prerequisite baseline repair restores two missing test-block braces in
  `DojoApiTest.kt`, explicitly approved by the user; compiler failure then full
  Android-suite success were observed before feature implementation.

Observed failing-then-passing checks cover generated Activity/actor transport,
bounded atomic cache/storage isolation, network identity handover/initial-state
races, offline warm/cold model restoration, section availability, blocked direct
writes, partial-read freshness, old-session response fences, accepted-write cache
failure, compatibility/401/426 persistence, disconnected transfer retry budget,
preserved ID/identity/ranges, missing-only reconnect chunks, and actor fallback.

Commands from repository root (JDK/SDK supplied through environment):

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME = 'C:\Users\35.HaRRy\AppData\Local\Android\Sdk'
uv run --project backend pytest backend/tests -q
uv run --project backend pytest backend/tests/test_client_generation.py -q
uv run --project backend ruff check backend/scripts/generate_clients.py backend/tests/test_client_generation.py
uv run --project backend python backend/scripts/generate_clients.py
git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
git diff --check
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
```

Only the final command is blocked by missing devices. Unit XML is under
`android/app/build/test-results/testDebugUnitTest/`; lint HTML/SARIF under
`android/app/build/reports/`; connected reports appear only after actual execution.

## Device matrix — not executed

Use **dedicated, unlocked test emulators only**. Tests create synthetic pairing
credentials, use a test DocumentsProvider, and temporarily change Wi-Fi/mobile
data settings before restoring them. Never run against an installation holding
real user pairing or media. Set `ANDROID_SERIAL` explicitly.

| Platform | Native seam | Required evidence | Result |
| --- | --- | --- | --- |
| API 33 | WorkManager | offline/reconnect pause intent and same-ID chunks; background/screen-off; read-only UI | blocked |
| API 34+ | UIDT JobService | same checks plus existing constrained-job wake and notification pause | blocked |
| API 29 | compatibility | offline cached startup, navigation, update gate | not run |
| Phone and tablet | Compose | light/dark, large text, wrapped history, TalkBack, disabled fields/drag/actions | not run |

New device scenarios are in `NetworkMonitorAndroidTest`, `UploadRuntimeAndroidTest`,
`BackgroundUploadTest`, `DojoAppTest`, `MediaEditorPanelTest`, `UploadPanelTest`, and
`OnboardingTest`. Existing upload/conflict suites remain compiled alongside them.
Check native Wi-Fi/mobile handover, a pending permission result after disconnect,
and fresh-only overwrite confirmation after reconnect. Screenshot/UI appearance,
frame timing, and accessibility are not claimed as verified.

Cold process restart/force-stop acceptance needs a **host-owned synthetic backend**;
the in-process MockWebServer fixture dies with the app. Confirm actual server upload
ID and acknowledged ranges before and after restart. Force-stop must be respected;
automatic execution while force-stopped is not promised.

## Scope and decisions

- One 4 MiB, schema-versioned snapshot in backup-excluded private storage, isolated
  by server and opaque pairing binding; update information also works before pairing.
- Cache contains metadata and latest 50 Activity events, not credentials, commands,
  drafts, or preview media. Cache miss and fetched-empty history have different UI.
- Full Activity browsing/settings remain #38; review implementation remains #36.
  Current pending review summaries are display-only; no absent review actions are
  represented as tested.
- Offline permits existing transfer pause/resume, historical navigation, and local
  server change. Retry/reselection/new uploads/conflict decisions and edits require
  fresh authoritative connectivity. No offline command replay queue.
- Constrained upload schedulers remain unchanged in kind; reconnect preserves an
  already-registered UIDT job rather than replacing it from background.
- Update download uses validated HTTPS URL and existing signed-release distribution.
  Android installer checks APK signature; no installer, release publication, signing
  secret, or private-repository visibility change is part of this task.

See [manual walkthrough](../rehberler/issue-37-android-cevrimdisi-deneme-rehberi.md).

## Whole-branch review and fix pass

One independent, read-only reviewer inspected `1a11eb1..dd4aa22`. No Critical
findings; six Important findings and one main-thread-IO finding were accepted.
The IO finding was regraded Important because credential verification holds the
same lock as durable snapshot writes. All entered one test-first author fix pass;
no second review or device-pass claim.

| Finding | Fix and observed regression |
| --- | --- |
| UI authority trails network/session state | Execution-time epoch/revision/session gate; recheck each mutation. `immediateDisconnectCannotEditOrSubmitBeforeCollectorRuns`, `newNetworkEpochCannotSubmitBeforeRevalidation`, and `delayedAssetRemainsPendingUntilExplicitFreshRetry` failed first, then passed. Uploaded asset stays pending rather than installing or reuploading automatically. |
| Offline resume leaves no durable wake | Explicit resume registers existing network-constrained work even offline; reconnect retains existing UIDT job. `offlineResumeRegistersConstrainedWorkBeforeProcessDeath` is compiled, **not executed**; both adapters/process-death acceptance remain blocked. |
| Delivered rejection lost on disconnect | Process received 401/426 under session fence regardless of connectivity; no retry charge. Authentication/status/chunk/conflict-refresh/decision cases failed first, then passed; definitive 409 also clears uncertain decision without replay. |
| Failed credential read erases replacement | Read/invalidation share SessionStore IO lock and revision; stale failure cannot clear changed credential/origin. Both `credentialReadFailureCannotDeleteReplacement` and `credentialReadFailureCannotEraseNewServerCache` failed first, then passed. |
| Replaced pairing leaves old protected UI | Observe credential revision; invalidate client/package/Activity and bootstrap current identity. Delayed-response and offline-restore identity checks failed first, then passed. Queued old background failure is also fenced. |
| Provider IO commits obsolete selection/replacement | Retain/verify/recheck before locked row commit; release uncommitted grant. Real UploadStore/SessionStore host checks pass after missing-helper red; delayed runtime-provider tests compile but **device execution is blocked**. |
| Credential verification blocks main | Session verification/decryption moves to IO; lightweight revision gates synchronous edits. Thread-recording regression failed first, then passed. No measured latency claim. |

Final host run passed unit suite, debug build, instrumentation build, and lint after
this pass. Device-only fixes are **host/build verified only**, not fully accepted.
There are no deferred Minor product findings; unexecuted native/UI tests are explicit
acceptance gaps, not lower-severity successes.

## Rulings during implementation

- Repair the existing API test's missing braces first, with user approval.
  Risk: test-only syntax; full suite was rerun before feature changes.
- Continue host-verified implementation without a dedicated emulator, while keeping
  device acceptance blocked. Risk: native/UI behavior still requires device proof.
- Preserve online draft edits during a pending command; busy blocks submissions,
  while disconnect/unverified state blocks editing. Risk: local draft UX, not parallel writes.
- Handle background session failures asynchronously to keep durable disk work on IO.
  Risk: consumers must observe completed state rather than assume synchronous return.
- Allow normal-refresh editor GETs in an old asset-only test, align dashboard/editor
  fixtures, and retain drafts when a stale editor cannot discard. Risk: stricter local
  discard UX; package mutation and stale-write protections remain tested.
- Preserve an existing constrained UIDT job on reconnect instead of replacing it from
  background. Risk: API 34+ wake behavior remains subject to the blocked device matrix.
- Move main-thread credential verification into the fix pass as Important rather
  than defer it as Minor. Risk: new revision/observer behavior needs native acceptance;
  host identity and IO-thread regressions pass.
- Keep actual adapter/callback/process-death behavior unaccepted without devices.
  Risk: native recovery defects may remain despite host tests.
- Keep screenshots, large text, and TalkBack unverified while retaining existing
  Material layout. Risk: visual/accessibility defects await device inspection.
- Do not claim filesystem/keystore timing; verify IO placement structurally.
  Risk: actual latency remains unmeasured.
- Exclude #36 review actions and #38 full feed/settings as approved. Risk: later
  integrations must consume the shared gate.
- Leave APK signing/publication to operator and installer. Risk: production update
  installation still needs release verification.
- Author-check concurrently written evidence/manual prose outside fixed review head.
  Risk: documentation mistakes are not covered by independent product review.
- Preserve the isolated worktree and ignored plan scratch while native acceptance
  is blocked; do not offer integration as completed acceptance. Risk: extra local
  scratch persists, but evidence and unfinished device checks remain recoverable.
