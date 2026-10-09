# Issue #33 — Android resumable uploads

Date: 2026-10-09. Branch: `feat/issue-33-android-upload`.

## Verdict

Implementation and host checks are present. **Device acceptance remains blocked**:
`connectedDebugAndroidTest` failed with `DeviceException: No connected devices!`.
No AVD, system image or SDK manager was available. No API 33/34+ background,
screen-off, notification, SAF or rendered UI behavior is claimed as verified.
Do not close #33 based on compilation alone.

## Host evidence

- Baseline Android unit tests and seven client-generator tests passed before edits.
- Full backend suite: **205 passed**, one existing Starlette/httpx deprecation warning.
- Generator regression verifies 2 GiB `Long` fields/ranges, nested conflict JSON,
  collection defaults and unchanged existing integer identifiers/version codes.
- Android unit suite covers authenticated transport, durable revisions/identity,
  pairing bindings, bounded/short-read preparation and cancellation, known-ID
  recovery after lost PUT/complete responses, pre-transfer rejection, pause races,
  retry exhaustion/reset, terminal statuses, storage/source failure, duplicate
  runners and delayed old-pairing errors.
- `:app:testDebugUnitTest :app:assembleDebug :app:lintDebug
  :app:assembleDebugAndroidTest` passed. Lint has no errors; dependency/update
  suggestions and existing UI/resource warnings are not device evidence.
- OpenAPI export/client generation reproduced committed artifacts. Backend OpenAPI
  and web DTOs are unchanged.

Commands (repository root; local SDK via `ANDROID_HOME` or untracked
`android/local.properties`):

```powershell
uv run --project backend pytest backend/tests -q
uv run --project backend ruff check backend/scripts/generate_clients.py backend/tests/test_client_generation.py
uv run --project backend python backend/scripts/export_openapi.py
uv run --project backend python backend/scripts/generate_clients.py
git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts android/app/src/main/java/com/dojo/aisomedo/api/GeneratedApi.kt
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
git diff --check
```

JUnit XML: `android/app/build/test-results/testDebugUnitTest/`.
Lint: `android/app/build/reports/lint-results-debug.html`.
Connected reports, when available: `android/app/build/reports/androidTests/connected/`.

## Device matrix — not run

Use **dedicated, unlocked test emulators only**. Instrumentation creates synthetic
credentials in the target app and grants access to test-only documents. Never run
it against an installation containing a user's pairing or media.

| Platform | Adapter | Evidence needed | Current result |
| --- | --- | --- | --- |
| API 33 | foreground WorkManager | Home/screen-off bytes advance; foreground notification; recovery/pause | blocked |
| API 34+ | UIDT JobService | same assertions; native job/notification; OS constraint stop | blocked |
| API 29 | foreground WorkManager | additional compatibility smoke check | not run |
| API 36 | UIDT JobService | additional compatibility/long-transfer check | not run |

Run separately on each representative emulator and record serial, API, test counts
and observed server IDs/offsets before accepting:

```powershell
# Point ANDROID_SERIAL at the dedicated emulator, then:
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
```

`BackgroundUploadTest` uses a real scheduled adapter, synthetic persistable
DocumentsProvider and local MockWebServer. Tests assert server counters, not
animated progress: advancing bytes after Home/screen-off; one initialization;
same ID and offsets `[0, 2097152, 4194304]` after ambiguous PUT/system stop;
notification pause survives Activity recreation; unknown-size oversize sends
neither initialization nor PUT; finalized status triggers shell refresh.
`UploadSourceAndroidTest`, `UploadRuntimeAndroidTest`, `UploadJobsAndroidTest` and
`UploadPanelTest` cover retained grants, shared-URI dismissal, auth fencing,
notification action shape and Turkish UI/progress semantics. These tests **compile
but have not executed**. Same-process Activity recreation is not process-death proof.

Additional manual scenarios still required:

1. Deny notification permission/channel; recoverable message, no crash or claim of
   visible notification. Force scheduler/foreground-start rejection; row retained
   with retry control. Verify unique connected-network scheduling.
2. Revoke document access, reselect identical bytes, reject changed bytes; dismiss
   one of two shared-URI rows without revoking the other's grant or deleting media.
3. Interrupt a multi-chunk upload, kill the test app process or force-stop it while
   a **host-owned** synthetic backend remains running. Check acknowledged ranges
   before reopening/resuming. Force-stop must not be bypassed. The in-process
   MockWebServer fixture cannot prove this scenario.
4. Verify 401/426 during a delayed old pairing cannot clear a newer credential;
   package-capacity/package-change rejection sends zero chunks; failed/404 upload
   starts anew only after explicit retry; conflict never overwrites automatically.
5. Inspect phone/tablet light/dark screenshots, large text, wrapped filenames,
   TalkBack progress/actions, navigation/rotation and notification tap to Paket.

UIDT uses job **3300 in namespace `dojo-uploads`** (not WorkManager's namespace).
On a dedicated API 34+ test emulator, inspect/stop with:

```text
adb shell dumpsys jobscheduler
adb shell cmd jobscheduler timeout -n dojo-uploads com.dojo.aisomedo 3300
```

## Scope and decisions

- No backend redesign, conflict-resolution UI, whole-media copy or background
  processing poller. WorkManager 2.10.5 is the only new product dependency.
- User select/resume/retry wakes a fresh platform runner; server ID and acknowledged
  ranges remain durable. This trades extra reconciliation GETs for avoiding a lost
  wakeup as a previous runner finishes.
- UIDT namespacing avoids WorkManager job-ID collision without custom Application
  configuration. Background auth events carry only opaque pairing bindings.
- Android suspension/force-stop is respected; durable recovery is promised, not
  uninterrupted execution under every OS condition.

Independent branch review and any corrections are recorded below when finished.
