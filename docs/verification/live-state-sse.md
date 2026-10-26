# Live-state synchronization verification

Date: 2026-10-21. Branch: `feat/live-state-sse`.

## Status

Implementation and deterministic client checks are present. **Real-stack
verification is incomplete; this branch is not verified for merge.** Docker is
unavailable in this session and no Android device/emulator is connected. Earlier
task results are not substituted for fresh verification of the current branch.

## Current evidence

| Check | Result |
| --- | --- |
| `npm --prefix web test` | 336 passed |
| `npm --prefix web run build` | Passed, including TypeScript |
| `web/node_modules/.bin/tsc.cmd --noEmit -p web/tsconfig.acceptance.json` | Passed |
| `npm --prefix web run test:browser` | 31 passed; one intentionally skipped mobile native-drag test |
| `npm --prefix web run test:browser -- live-state.spec.ts` | Eight passed, desktop and mobile |
| Core Ruff / mypy | Passed; 36 source files checked by mypy |
| Backend Ruff / mypy | Passed; 26 source files checked by mypy |
| Worker Ruff / mypy | Passed; four source files checked by mypy |
| `uv run --project backend pytest ops/tests/test_acceptance.py -q` | 31 passed |
| OpenAPI export and client generation | Reproduced all 72 paths; generated files unchanged |
| Core full pytest suite | 571 passed, nine skipped, 230 setup errors, two failures; PostgreSQL cases blocked by Docker |
| Backend full pytest suite | 230 passed, 13 setup errors; PostgreSQL cases blocked by Docker |
| Worker full pytest suite | 141 passed |
| Android debug unit tests / lint after review fixes | 277 passed; `lintDebug` passed |
| Fix-pass focused checks | Web 41 passed; core render 24 passed; backend listener-health 1 passed; focused Android 112 passed; Ruff and mypy passed |
| New backend cross-process integration test | Blocked in PostgreSQL fixture setup: Docker named pipe unavailable |
| Android `LiveStateTest` | Test APK compiled; connected execution failed: `No connected devices!` |
| Isolated gateway acceptance | Blocked before stack creation: Docker image inspection could not reach the daemon |

The core tests reported as failures, rather than setup errors, are
`test_concurrent_same_version_accepts_once[True]` and
`test_clear_removes_only_package_files_records_and_pending_work[postgres]`.
Both request their PostgreSQL fixture inside the test and fail at the same
unavailable Docker connection. They are not passing results.

## Review fix pass

Six Important review findings have deterministic regression coverage. No
Critical finding was reported. The fixes are:

- Listener lookups are bounded by a PostgreSQL statement timeout, and stream
  readiness/heartbeats expire when the listener makes no progress. The
  Docker-free `backend/tests/test_live_health.py` blocks a fake lookup and
  proves the stream resyncs and stops advertising readiness instead of
  emitting a false heartbeat.
- Android retains failed snapshot resources and retries their union; an
  unrelated invalidation cannot announce `LIVE` after the initial full sync
  failed.
- Web draft deletion leaves a revision-bearing tombstone. A stale tab at the
  deleted revision cannot overwrite a recreated draft, while a genuinely new
  draft can start after the tombstone.
- Web rollover discards delete the replaced package's draft before rebinding
  the editor to the replacement package; later input is stored under the new
  package key.
- Android rollover discards delete the original package draft before binding
  the clean replacement state; a deletion failure restores the original
  in-memory draft and leaves its durable file intact.
- Render digests include the effective default logo, and the same resolved
  branding is used by the reel builder. Changing only the default logo changes
  the digest.

These checks are unit/JVM/fixture checks. They do not replace the blocked
PostgreSQL, real-gateway, or connected-device checks listed above.

## Coverage and limits

Deterministic browser checks use actual Fetch-stream parsing and IndexedDB, not
an in-memory storage mock. They cover incomplete-input reload, read-only startup,
atomic competing-tab compare-and-replace, independent-profile edits, whole-batch
conflict rejection, disconnect locking, and ten virtual idle minutes with no new
state requests. These browser endpoints are fixtures; they do not establish
PostgreSQL or reverse-proxy correctness.

Android JVM checks cover fragmented UTF-8/CRLF/multiline streams, oversized and
incomplete frames, cancellation of a blocked OkHttp socket read, stream-specific
deadlines, heartbeat-only operation without snapshot polling, invalidations
during reads and failed reads, foreground admission, and terminal authorization
failure. Disk tests cover incomplete drafts, failed atomic replacement preserving
the previous file, identity separation, unsupported-record quarantine, conflicts,
and lost-save recovery without replay. HTTP resource versions additionally fence
late responses and snapshots older than an observed invalidation.

`backend/tests/test_live_integration.py` starts two independent API processes and
a worker process against one disposable PostgreSQL database. It checks worker
invalidation delivery, burst convergence, current HTTP snapshot/version pairs,
listener termination/reconnection, streaming headers, and revocation of open
connections. Its assertions have not executed in the current environment.

`web/acceptance/live-state.spec.ts` uses the existing isolated TLS/gateway stack,
real upload processing, two separately paired browser profiles, real grouped
commands, local recovery, an idle-request observation window, and revocation. It
does not contact Instagram or add production-only fixture endpoints. The seed
provides two additional one-time browser codes; the acceptance report requires
the new named scenario as well as the two existing publication scenarios.

Compose assertions and `LiveStateTest` cover read-only draft restoration before
stream/snapshot readiness, disabled inputs/drag/actions, explicit saving, and
storage warnings. Compilation is not a substitute for running them on a device.
No fresh device screenshots or real-gateway streaming claims are made.

## Reproduce blocked checks

With Docker available, run:

```powershell
uv run --project dojo-core pytest dojo-core/tests -q
uv run --project backend pytest backend/tests -q
uv run --project worker pytest worker/tests -q
uv run --project backend pytest backend/tests/test_live_integration.py -v
uv run --project backend python ops/acceptance/run.py --image-tag live-state-sse --build
```

The acceptance runner creates only its own isolated project, throwaway
credentials, certificate, and evidence directory. Do not point these tests at an
installation database or reuse an installation environment file. Inside that
configured disposable browser container, the focused scenario is:

```sh
npm run test:acceptance -- live-state.spec.ts
```

With a connected Android device/emulator and the SDK configured:

```powershell
android\gradlew.bat -p android :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.LiveStateTest
android\gradlew.bat -p android :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.MediaEditorPanelTest
```

Existing upload transfer, worker scheduling, push registration, and publication
reconciliation timers are intentionally unchanged. The no-polling checks concern
foreground live-state reads; SSE heartbeats and reconnect backoff are transport
controls, not database scans or periodic snapshot queries.
