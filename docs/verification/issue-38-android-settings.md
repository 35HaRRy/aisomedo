# Issue #38 — Android activity and settings

Approved scope: retain recent Activity history; expose plan, branding, Instagram
status/reconnect and read-only consent in Settings; persist reminder policy using
the existing API. Reuse onboarding editors and shared offline/session guards.

## Checklist

- [x] Explore existing flow and prerequisite tickets (all closed).
- [x] Present bounded design and obtain approval.
- [x] Add failing checks, implement and verify focused tests.
- [x] Run full suites, Android compilation/build and lint.
- [x] Review changes and resolve finding.

## Host evidence — 2026-10-14

- Android full unit suite: **247 tests, 0 failures/errors/skips**.
- `assembleDebug`, `assembleDebugAndroidTest` and `lintDebug`: exit 0.
  Lint reports 31 warnings, no errors; existing compiler icon-deprecation notice
  remains. Successful lint is not a claim that all warnings were resolved.
- Backend: **210 passed**, one existing Starlette/httpx deprecation warning.
- Core: **733 passed, 4 skipped**, 22 dependency deprecation warnings.
- Worker: **140 passed** (263 seconds).
- Web: **288 passed**; TypeScript typecheck exits 0.
- Client generator: **9 passed**; generator Ruff check and `git diff --check`
  exit 0. Regeneration changes only the intended Android reminder DTOs;
  backend OpenAPI and web DTO diff remain empty.

Commands from repository root (JDK set to Android Studio's bundled JBR):

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
.\android\gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest --console=plain
uv run --project backend pytest backend/tests -q
uv run --project dojo-core pytest dojo-core/tests -q
uv run --project worker pytest worker/tests -q
uv run --project backend pytest backend/tests/test_client_generation.py -q
uv run --project backend python backend/scripts/generate_clients.py
uv run --project backend ruff check backend/scripts/generate_clients.py
git diff --check
# From web/:
npm test
npm run typecheck
```

Initial combined Python collection failed because backend and worker both have
`test_health.py`; running their full suites separately resolves collection without
changing product code. Initial worker run hit a 240-second timeout; its complete
rerun passed with a longer allowance. Initial web run failed
`successful approval HTTP response still displays publication failure after review refresh`
in `src/reviews/ReviewFlow.test.tsx`; isolated file and subsequent full suite passed
without changes to web source. That intermittent failure is recorded, not fixed
or claimed permanently resolved.

## Regression coverage and review

Five new model tests exercise actual session storage, HTTP transport and model:

- Settings loads configuration without opening onboarding; restored Settings
  destination reloads server state and preserves edited reminder draft.
- Reminder policy PUT carries authenticated positive interval and overnight
  window; server read-back and recreation restore persisted values.
- Invalid interval/window does not send; rejected save retains dirty draft.
- Remote refresh preserves edited fields, updates untouched fields and marks
  changed policy; explicit reload adopts server values. Immediate disconnect
  prevents submission even before the connectivity collector runs.
- Interval-only edits preserve second-bearing boundaries, including a window
  whose start/end share a minute.

Observed red-green checks: initial Settings navigation assertion failed before
configuration loading was added; reminder validation failed before validation;
review regression failed before removing time truncation. The first reminder
test attempt also failed compilation on the absent model save method; only
subsequent executable failures are treated as behavioral evidence.

Two new Compose tests compile: Settings exposes existing editors/reconnect and
read-only consent without wizard navigation; offline Settings disables writes
and reconnect while keeping consent and navigation readable. These tests have
**not executed**. Existing Activity transport, actor fallback, history empty/missing
and cached-offline checks remain unchanged.

Parallel static review against baseline `4f6155f`:

- **Standards/correctness:** one P2 finding, reminder-time precision loss. The API
  stores seconds; preserving complete server values fixes interval-only edits.
  Regression failed first and passes after fix.
- **Spec:** zero blocking findings; all requested surfaces are wired. Device
  acceptance remains pending, not implied by host builds.

No dependencies, backend endpoints, offline command queue, release or signing
changes added. Existing onboarding editors and shared session/freshness guards
are reused. Local commit only; no push or issue closure.

## Device acceptance

No devices or AVDs were available at implementation start. Native UI execution,
phone/tablet screenshots, dark mode, large fonts, picker callbacks and real
Instagram browser return require device verification. Instrumentation compilation
alone does not prove these behaviors.

Executed command:

```powershell
.\android\gradlew.bat -p android :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.dojo.aisomedo.ui.DojoAppTest' --console=plain
```

Fails with `DeviceException: No connected devices!`. `adb devices -l` reports no
devices; `emulator -list-avds` returns none. An initial unquoted Gradle property
was split by PowerShell and rejected during task selection; the quoted rerun
above reached the actual device gate.

Before accepting #38 on device, verify recent history refresh/empty states,
plan/branding/reminder persistence after app restart, reconnect browser return
and account selection, accepted/unaccepted consent display, offline controls,
phone/tablet navigation, dark theme and enlarged system fonts. Keep issue open
until native acceptance evidence exists.
