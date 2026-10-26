# Issue #35 — Android montage media management

Date: 2026-10-10.

## Scope

The existing Paket destination now reads `/api/packages/active/editor` without
creating a package. Finalized media follows the saved montage order; removed media
has a separate restore section. Removal does not delete source files.

- Drag the dedicated handle to a before/after insertion marker; order saves only
  on drop. Edge holding scrolls the package viewport. Gesture cancellation and
  Back cancel the drag without writing. Up/Down buttons provide an accessible
  alternative. Trim fields never initiate a drag.
- Edit retained video ranges in seconds, add/remove ranges, or restore whole-video
  playback. Existing multiple ranges on other videos are preserved. Decimal comma
  is accepted; ranges must be finite, within source duration, non-overlapping,
  and at least one 25 fps frame long.
- Proposed duration includes photos and intro/outro cards. Invalid, unknown or
  over-limit duration blocks trim saves; feedback asks for trimming/removal, not
  automatic truncation. Backend validation remains authoritative.
- Every mutation carries the loaded package folder. Uncertain writes/reads fence
  further edits until explicit refresh. Concurrent changes and package switches
  preserve unsaved drafts; discard is required before applying an old draft to a
  different package. Pairing/update failures use the existing session gate.

No new product dependency, backend endpoint, or photo-duration editor.

## Verification

Final host checks:

- Android: **82 unit tests passed**, zero failures/errors/skips. App and
  instrumentation APKs assembled; lint completed without errors.
- Backend: **206 passed**, one existing Starlette/httpx deprecation warning.
- Dojo core: **688 passed, 4 skipped**, 19 deprecation warnings from testcontainers
  and Firebase multicast tokens.
- Client-generation Ruff checks passed. Kotlin/web clients reproduce exactly from
  the committed OpenAPI schema; backend schema and web output are unchanged.
- `git diff --check` passed.

Lint still reports dependency/update, target API, private resource, plural-candidate,
missing application icon and KTX suggestions. No dependency upgrades or unrelated
UI cleanup was attempted.

Independent read-only review found one important stale-write bypass: discarding a
draft cleared the failed-read fence. The new regression failed before the fix;
discard now preserves the fence until successful refresh. The final full unit
suite includes this regression and the save/read-back/package-change checks.

**Device acceptance is not verified.** `adb devices` returned no connected
devices; `emulator -list-avds` returned no AVDs. Compiling instrumentation does not
prove gesture behavior, auto-scroll, accessibility or visual quality on a device.
`connectedDebugAndroidTest` failed with `DeviceException: No connected devices!`.
Do not close #35 based on host checks alone.

Commands from repository root:

```powershell
uv run --project backend pytest backend/tests -q
uv run --project dojo-core pytest dojo-core/tests -q
uv run --project backend ruff check backend/scripts/generate_clients.py backend/tests/test_client_generation.py
uv run --project backend python backend/scripts/generate_clients.py
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest
./android/gradlew.bat -p android :app:connectedDebugAndroidTest
git diff --check
```

Host reports: `android/app/build/test-results/testDebugUnitTest/` and
`android/app/build/reports/lint-results-debug.html`.

## Device handoff

Use a dedicated test emulator/installation, not one holding personal pairing or
media. Existing instrumentation uses synthetic credentials/documents.

1. Run `MediaEditorPanelTest`: before/after drag insertion, no write before drop,
   cancel/blocked drag, accessible movement, invalid/valid trims and stationary
   edge auto-scroll. Run the full instrumentation suite afterward.
2. With a test backend, upload a photo and two videos. Drag first to last, reload
   Android and web, and verify persisted order. Cancel a drag with Back and verify
   no request/order change. Upload another file; prior order stays unchanged.
3. Remove then restore a video; verify source retained and restored saved ranges.
   Change one video's ranges while the other has multiple saved sections. Save,
   reload both clients and confirm every section; reset means whole video.
4. Exceed the duration limit including cards. Verify explicit excess feedback and
   disabled save; remove/trim enough media to recover. Unknown source duration,
   overlapping ranges, partial text and non-finite values must not save.
5. Change the package or montage in web while Android has a draft; refresh and
   verify no silent overwrite or old-package retargeting. Interrupt a write/read,
   revoke pairing and raise minimum version: no automatic retries or stale writes.
6. Capture phone/tablet light/dark screenshots, long filenames, large font and
   TalkBack action labels. Check narrow portrait and keyboard-visible trims.
