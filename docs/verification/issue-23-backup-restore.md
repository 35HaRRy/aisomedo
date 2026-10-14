# Issue #23 — Manual encrypted backup and restore verification

Date: 2026-10-14. Production data, credentials and `dojo-prod` were not used.

## Feature evidence

- Linux backup/deployment unit tests: **87 passed**, no skips.
- Real age checks cover round trip, wrong identity, changed ciphertext and truncation.
- Real Linux Compose/PostgreSQL recovery: **4 passed**, no skips (263.85 s).
  - Existing installation: original database values and exact environment restored;
    binary/empty-directory media restored; post-backup extra file removed; two
    worker replicas retained.
  - Monitoring installation: external synthetic Firebase credential restored and
    relocated to private configuration; other env content preserved.
  - Fresh installation after disposing fixture resources: database/config/media
    restored and all application services healthy.
  - Injected failure after actual database/media replacement: writers remain
    stopped; encrypted safety archive remains available.
- CI required-step test: **1 passed** on Linux. A simulated test-runner failure
  propagates as a failing ops step; integration-required mode cannot silently skip.
- Ruff for new CLI and all ops tests: passed. New CLI mypy: passed.
- Core/backend/worker mypy: passed (34/23/4 source files).
- Turkish guide: **7 PowerShell blocks** parsed successfully; no Python or SQL
  source embedded in command examples.

## Regression evidence and limitations

| Check | Observed result |
| --- | --- |
| Core Python suite | 737 passed; 22 upstream deprecation warnings |
| Backend Python suite | 209 passed, 1 skipped; upstream Starlette warning |
| Worker Python suite | 139 passed, 1 failed; repeat produced same failing test |
| Full ops Python suite | Final run result will be recorded after completion |
| Web unit suite | 288 passed |
| Web production build | Passed, including TypeScript checking |
| Browser suite | 21 passed, 1 skipped (mobile native-drag scenario) |
| Android Gradle | Build, unit-test task, lint and instrumentation compilation succeeded; many tasks were up-to-date |

**Full regression suite is not entirely green.** Existing
`worker/tests/test_monitoring.py::test_run_uses_monotonic_deadlines_so_a_slow_turn_does_not_shift_them`
uses the real monotonic clock for its first assertion and expects a 60-second wait
within about 60 microseconds. Linux observed overhead exceeded that tolerance
(66–89 microseconds). No worker source or test was changed for this unrelated timing
failure. This result is not hidden by the passing issue-23 recovery tests.

The original combined Python-suite command also stopped during collection because
backend and worker both contain `test_health.py`. Suites were subsequently invoked
separately, matching CI, rather than deleting caches or renaming unrelated tests.

No Android device instrumentation test, real Instagram publication, real FCM send,
live deployment, external DNS/TLS provisioning or production restore was performed.
Integration health exercises real gateway HTTP/API routing inside the disposable
project; the production public-HTTPS helper is substituted at that external boundary.

## Test environment

- Windows host with Docker Desktop Linux engine; Python project tools available.
- Ubuntu WSL exists but Docker integration is disabled. This is an environment
  limitation, not a passing WSL test.
- Linux test runner: Python 3.12.14, official distro age 1.2.1, Docker/Compose,
  FFmpeg and existing workspace dependencies. Windows crypto checks additionally
  used official age 1.3.2 downloaded into private temporary test tooling.
- Verification images built locally from current Dockerfiles:
  `dojo-backend-verify:issue23`, `dojo-worker-verify:issue23`,
  `dojo-gateway-verify:issue23`; application database image `postgres:18`.
- Test runner accesses the existing Docker daemon and a dedicated test-data volume.
  Temporary fixture projects use random `verifybackup...`/`verifydeploy...` names;
  generated secrets are synthetic, private and excluded from Git.
- Registry lookup is mapped to local verification images in fixtures only; release
  metadata validation remains active. The production project name is not overridden
  in product CLI options.

## Commands behind evidence

Executed inside the isolated Linux test runner with fixture data visible to Docker:

```text
pytest -p no:cacheprovider ops/tests/test_backup.py ops/tests/test_deploy.py -q
REQUIRE_BACKUP_INTEGRATION=1 VERIFY_IMAGE_TAG=issue23 pytest -p no:cacheprovider ops/tests/test_backup_integration.py -q
pytest -p no:cacheprovider ops/tests/test_workflows.py::test_backup_integration_step_is_required -q
pytest -p no:cacheprovider dojo-core/tests -q
pytest -p no:cacheprovider backend/tests -q
pytest -p no:cacheprovider worker/tests -q
REQUIRE_BACKUP_INTEGRATION=1 REQUIRE_DEPLOY_INTEGRATION=1 VERIFY_IMAGE_TAG=issue23 pytest -p no:cacheprovider ops/tests -q
```

Windows tooling commands additionally ran ruff/mypy, `npm test`, `npm run build`,
`npm run test:browser`, and Android Gradle's `testDebugUnitTest`, `assembleDebug`,
`lintDebug`, `assembleDebugAndroidTest` tasks.

First integration attempt exposed two **fixture** defects: invalid monitoring low
threshold 0, and top-level unsuffixed media folders affected by normal startup repair.
Fixtures now use valid 0.1/1 hysteresis and `branding` subdirectories. All four real
recovery scenarios subsequently passed; application business behavior was not changed.

## Operational decisions

- Recovery uses recorded env settings; shell interpolation overrides are refused.
- Existing restore retains database/role and persistent storage identities.
- Matching PostgreSQL image must be available; image layers are not archived.
- Failed destructive restore is recovered from original/safety archive on a fresh
  target, not by restarting a partial installation or silently bypassing safety capture.
- Plaintext staging is private and unlinked on handled exit, not securely erased.
- Restores trust archive provenance: authenticated encryption is not sender signing.

Review findings and final disposition will be added after independent review.
