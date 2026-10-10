# Issue #34 — Android filename conflict resolution

Date: 2026-10-09. Branch: `feat/issue-34-android-conflicts`.

## Status

Implementation and host checks are present. **Device acceptance is blocked**:
`connectedDebugAndroidTest` fails with `DeviceException: No connected devices!`.
Compose instrumentation compiles but has not executed. No screenshots, TalkBack,
video playback, phone/tablet layout, rotation, or lifecycle behavior are claimed as
device-verified. Keep #34 open until that acceptance evidence exists.

## Host evidence

- Android unit suite: **88 tests, 0 failures, 0 errors, 0 skipped**.
- Debug APK, instrumentation APK, and lint tasks pass. Lint reports no errors;
  dependency/update suggestions and pre-existing resource/UI warnings remain.
- Backend suite: **205 passed**, one existing Starlette/httpx deprecation warning.
- Client-generator regressions and Ruff pass. Regeneration adds only the Android
  `ResolveConflictIn` DTO; backend OpenAPI and browser DTOs are unchanged.
- Behavioral red/green probes cover conflict refresh, missing primary metadata
  recovery, preventing replay after unchanged conflict polls/restart/408/429,
  cross-client skips, the gap between aborted-state and audit writes, and clearing
  pending decisions after definitive 404. New API/state tests
  initially failed compilation because their requested feature APIs did not exist;
  they now pass. Instrumentation assertions were not observed running red or green.
- Engine checks cover all decisions, bulk responses belonging to another upload,
  Unicode compatibility encoded by shared target IDs, unrelated conflicts, lost
  responses, skipped versus expired outcomes, durable pending decisions, definitive
  rejection, authoritative audit outcomes, target/confirmation validation, and stale pairing responses.
- Transport checks cover authenticated and encoded preview/resolve paths, streamed
  size bounds, redirect rejection, cancellation cleanup, and no automatic retry.
- UI-state checks cover explicit consent, loaded-preview gating, and consent reset
  on target, decision, bulk scope, or preview changes; malformed target data cannot
  enable overwrite.

Commands from repository root:

```powershell
$env:ANDROID_HOME = 'C:\Users\35.HaRRy\AppData\Local\Android\Sdk'
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
uv run --project backend pytest backend/tests -q
uv run --project backend ruff check backend/scripts/generate_clients.py backend/tests/test_client_generation.py
uv run --project backend python backend/scripts/generate_clients.py
git diff --exit-code -- backend/openapi.json web/src/api/openapi.ts
git diff --check
```

Reports: `android/app/build/test-results/testDebugUnitTest/` and
`android/app/build/reports/lint-results-debug.html`.

## Design and recovery

The existing Paket upload rows now show three decisions and an apply-to-all
checkbox. Keep-selected requires a valid selected target, a successfully decoded
image or prepared video, an irreversible warning, and fresh explicit consent.
Missing/failed previews leave keep-both and keep-target available.

Bulk mutation is performed once by the server. Its response can describe another
upload, so local rows reconcile by their own server IDs. Compatibility is based on
package and server collision target IDs, not Android lowercase heuristics. A
durable pending decision blocks another mutation until status is known. Aborted
uploads are classified using authenticated, paginated activity audit evidence:
`conflict.resolved` with `keep_target` means skipped; `upload.expired` or
`upload.aborted` means unavailable. Missing audit evidence remains uncertain;
neither an unchanged conflict poll nor an aborted-state/audit-write gap releases
the pending marker. This also handles decisions made by another client without a
backend contract change. Audit pagination is deliberately reused rather than
adding an outcome endpoint; very large histories may warrant a scoped outcome field.
Refresh also recovers decisions made in another client and schedules receiving
rows through the existing background upload adapter.

Previews use existing same-origin, redirect-disabled authenticated transport.
Normalized JPEGs are sampled for display; MP4s use native `VideoView` controls.
Only previews are temporarily copied, not selected upload source documents. The
private preview cache is bounded at 10 MiB per JPEG / 512 MiB per MP4 and removed
on failure, cancellation, composition disposal, or the next process startup.
Larger/slow previews fail safely and cannot authorize overwrite. No new product
dependency, backend mutation logic, or persistent bulk preference was added.

## Required device acceptance

Use a **dedicated, unlocked emulator only**. Existing instrumentation creates
synthetic pairing credentials and document grants; do not run against a user's
paired installation or real media.

```powershell
# After selecting a dedicated emulator via ANDROID_SERIAL:
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
```

1. Upload synthetic colliding photos/videos; verify target filename, byte count,
   upload time, target ID, image preview, and video play/pause controls.
2. Keep-both preserves the target and receives a server numeric suffix.
   Keep-target shows skipped, transfers no chunks, and remains skipped after
   restart. Keep-selected changes the selected target only after visible warning,
   loaded preview, and explicit consent; confirm server audit record.
3. Apply each decision to two Unicode/casefold-compatible conflicts plus an
   unrelated conflict. Only compatible conflicts change; later selections do not
   inherit the decision. Multi-target overwrite uses the exact previewed ID.
4. Disconnect after resolution POST and before GET: outcome remains uncertain,
   controls cannot send a second decision, refresh recovers without another POST.
   Test process death against a host-owned server (in-process fixtures cannot prove
   survival of server state across app termination).
5. Fail/cancel preview, change target, change bulk scope, change decision, refresh,
   rotate, and navigate away: no stale consent; failed preview cannot overwrite.
   Check temporary preview cleanup and no video playback after backgrounding.
6. Exercise 401/426 and delayed old-pairing responses. Only matching pairing may be
   affected; no credentials leak into preview paths, UI messages, or redirects.
7. Capture phone/tablet light/dark and 1.3x text screenshots; inspect long Turkish
   filenames, scroll reachability, disabled states, TalkBack radio/checkbox labels,
   warnings, and status announcements. No web detector was used for native code.

## Review corrections and remaining limits

The initial independent read-only review requested changes. Its four important
findings and one minor finding were addressed:

| Finding | Correction | Evidence |
| --- | --- | --- |
| Unchanged conflict poll cleared uncertain mutation protection | Keep pending decision until authoritative transition or definitive rejection; 408/429 do not release it | Host red/green tests, including restart and audit-write gap |
| Refresh could cancel preview by changing only revision and strand loading | Suspend refresh; dispose old preview and reload after completion; active-coroutine fence cancellation becomes recoverable failure/retry | Source check; native regression compiles, execution blocked |
| Video decoder error retained downloaded file | Stop/release playback before deleting private file and removing player | Source check; bad-MP4 cleanup regression compiles, execution blocked |
| Cross-client keep-target appeared as expiry | Query existing activity audit, paginate and validate cursor; use authoritative decision instead of guessing from local intent | Host red/green cross-client, expiry, missing-evidence and pagination tests |
| Cancellation between file creation and dispatch could lose cleanup ownership | Set ownership inside IO creation block before cancellable delivery | Source check; no device claim |

The follow-up independent verdict attempt failed with **usage limit reached**.
The implementation thread performed a scoped code-only check and reran host
verification; it does not replace an independent endorsement or rendered review.
Native review disposition remains **recapture** because no device screenshots or
executed native tests exist. The original UI identity is preserved: existing
`DojoTheme`, Material3 controls, semantic color/type roles, and scroll container;
no new visual system or design documentation was invented for this extension.

One final Gradle verification initially timed out during lint at 120 seconds;
the rerun with a 300-second timeout completed successfully, as did the subsequent
full verification after the audit-write-gap regression fix. No timed-out run is
counted as a pass. Existing Kotlin icon deprecation and lint/dependency warnings
are not represented as zero-warning output.
