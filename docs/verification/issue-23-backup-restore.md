# Issue #23 — Manual encrypted backup and restore verification

Date: 2026-10-14. Production data, credentials and `dojo-prod` were not used.

## Feature evidence

- Linux backup/deployment unit tests on final source: **108 passed**, no skips.
  Added regressions cover resolved custom-volume collisions, unsupported
  external/bind-backed/aliased storage, fresh-target shell overrides, and signals
  during application restart (SIGINT/SIGTERM/SIGHUP), unrelated-directory permission
  preservation, CRLF/BOM/export formatting, and producer/consumer manifest-size consistency.
- Real age checks cover round trip, wrong identity, changed ciphertext and truncation.
- Real Linux Compose/PostgreSQL recovery: **4 passed**, no skips; all four also
  passed in final-source full ops run (**148 passed, 3 Android-signing skips**, 529.37 s).
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
| Full ops Python suite before review fixes | 127 passed, 3 skipped (Android signing prerequisites) |
| Full ops Python suite after initial review fixes | 136 passed, 3 skipped |
| Full ops Python suite after final root/env guards | 148 passed, 3 skipped (Android signing prerequisites) |
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
- Environment bytes, including CRLF/BOM, are preserved; monitoring changes only its
  credential host-path assignment, preserving export/spacing/line endings.
- Invalid/non-installation roots and shared sticky directories are rejected before
  permission changes or installation-lock creation.
- Manifest metadata is limited to 8 MiB on creation and restore, so backup cannot
  claim success for an archive that its own decoder rejects on size.

## Independent review and disposition

Pinned range: `ed9818a...c4ffb39`. Two read-only reviewers assessed standards and
spec separately; no second review was dispatched after fixes.

### Standards

No hard documented-standard violations. Two Important findings were confirmed:
restart interrupts escaped recovery, and fresh restores skipped shell-override
refusal. Both were reproduced by failing tests and fixed. One Minor finding is
deferred: generic validation failures suppress otherwise safe operator diagnostics.

### Spec

One Critical finding was confirmed: fresh restore could reuse a custom-named
existing volume outside the project prefix. Prospective storage now rejects external,
bind-backed and aliased volumes or unexpected mounts, and fresh recovery checks every
resolved destination volume for existing resources. Regression tests failed before
the fix and pass afterward. Two Important findings duplicate the standards findings
and were fixed by the same regressions. One Minor finding is deferred: destructive
failure guidance includes the safety archive but hides the original static step label.

Review counts at pinned baseline: Standards **2 Important + 1 Minor**; Spec
**1 Critical + 2 Important + 1 Minor**. Unique Critical/Important findings: **3**, all
fixed with RED→GREEN evidence. Two diagnostic Minor findings remain deferred; neither
permits mutation without safety capture or a success claim after failed restore.

Final author checks also reproduced and fixed three safety/faithfulness gaps:
oversized manifests could be emitted despite decoder limits; invalid root paths
were chmodded before installation recognition; env text I/O normalized CRLF and
discarded BOM/export formatting around relocated credentials. The failing cases
now pass; monitoring integration additionally uses CRLF and compares exact bytes.

The spec reviewer declined to judge live restore/external TLS, unrelated worker
timing failure, and then-pending ops results. Those remain explicit environment/scope
limits above, not implicit successful verification.

### Execution decisions and costs

- Current `development` branch used, as requested by implement workflow: no worktree isolation.
- Shell Compose overrides refused: operator must unset those variables before recovery.
- Failed destructive restore recovers on fresh target: spare clean host/resources required.
- Exact PostgreSQL image required locally: operator must retain or fetch matching image.
- Docker test runner substituted for disabled WSL integration: temporary runner/test-data volume needed.
- Python suites run separately like CI: four commands, avoiding duplicate module-name collection.
- Unrelated worker timing failure preserved: full regression suite remains red and is reported honestly.
- Review starts at pre-implementation `ed9818a`: earlier unrelated branch history excluded.
- Replace-not-merge coverage uses real Docker round trip rather than a separate
  mocked unit name: that coverage requires Docker.
- Unexercised production restore/DNS/TLS stays unverified: operator must prepare and
  validate real host prerequisites separately.
- Pending review-time ops status is settled by measured test outputs, never assumption.

Final source is verified by the complete ops run, including real deployment rollback
and all four encrypted recovery scenarios. Remaining regression failure is the
unchanged worker timing test reported above; no entirely-green claim is made.

Feature-specific checks passed, but this report does **not** certify an entirely
green regression suite or authorize merging, deployment, publishing or production restore.
