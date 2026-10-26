# Issue #40: deployed-stack acceptance

Run from repository root with Linux Docker containers, Docker Compose v2,
and the existing `uv` workspace synchronized:

```sh
uv sync --all-packages --frozen
uv run --project backend python ops/acceptance/run.py --image-tag issue40 --build --output artifacts/acceptance
```

The first run builds the production backend/worker/web gateway plus a Chromium
tool image. Internet access is needed for builds and pulling PostgreSQL; the
running test network is internal and cannot contact Meta or Firebase. CI reuses
its verification images by omitting `--build` and setting `--image-tag` to the
commit SHA. The normal ops job and required aggregate gate both workflows.

## What passes mean

Two serial Chromium cases use the real built web application without request
interception. Setup pairs a browser and synthetic Android notification recipient,
connects a fixture Instagram account, configures logo/caption/plan/consent, and
sets a delivery window that includes the scheduled boundary.

- Scheduled: advance shared clock past Monday's due time, wait for worker render
  and review notification, play preview, approve and confirm completed package.
- Manual: upload a new package, request review in the dashboard, then perform
  the same review and completion checks without moving the recurring cadence.

Each case hashes authenticated preview bytes and compares them with video actually
fetched by fake Meta over trusted HTTPS. Caption, external identifiers, container
and publish counts are checked. A later worker turn must not publish again.
The runner also checks two documented `-completed` folders and their manifests
exist on the shared filesystem volume.

Only dependency composition changes in the test entrypoint: real HTTP Meta
publisher targets the fake endpoint, notifier sends to collector, clock reads
fixture time. Ordinary API routes, PostgreSQL schema initialization, scheduler
leadership, rendering, jobs, media validation, and publication rules still run.
No production test API or weakened HTTPS validation is introduced.

## Isolation and evidence

Every invocation uses a random `dojo-acceptance-*` Compose project, fresh named
volumes, synthetic env file and throwaway CA. It never reads `ops/.env` or uses
production volume names. CA trust is installed only inside test containers.
No host listener is published. Cleanup runs even after startup/browser failure;
cleanup errors produce a failing exit code and name the owned project.

Each invocation creates a unique subdirectory under the output directory, so an
old successful report can never satisfy a new run. That subdirectory contains
Playwright JSON report, screenshots/traces, bounded
Compose logs, service status, external-service evidence and filesystem evidence.
Treat traces as private diagnostics: browser cookies and synthetic tokens may
appear in traces. Pairing seed file is deleted before handoff; private CA/server
material stays in temporary scratch, not uploaded artifacts.

Exit zero requires both named cases passing exactly once with no retries/skips,
real completed-folder evidence and successful cleanup. Missing tools/images or
empty reports fail, never count as successful skipped acceptance.

This does not prove real Meta account authorization, Firebase delivery, Android
device behavior, publicly issued TLS certificates or public internet reachability.
Existing domain, API, browser and Android suites retain broader failure coverage.

## Recorded verification — 2026-10-16

Local Windows host with Docker Linux containers:

| Check | Observed result |
| --- | --- |
| Real deployed acceptance | 2 passed; 0 skipped, unexpected, or flaky |
| Shared filesystem | 2 completed folders with manifests |
| Fake Meta | 2 containers, 2 publications; each digest/caption matches review |
| Notifications | Review and publication-confirmed delivery for both packages |
| Core Python suite | 733 passed, 4 skipped |
| Backend Python suite | 210 passed |
| Worker Python suite | 140 passed |
| Web unit suite | 290 passed with `--maxWorkers=2` |
| Existing web browser suite | 21 passed, 1 existing mobile-drag skip |
| Android | Unit tests, debug build, lint and instrumentation compilation successful |
| Types/lint | Core/backend/worker mypy, acceptance mypy and Ruff passed; web build passed |

Acceptance evidence is under the ignored local directory
`artifacts/acceptance/dojo-acceptance-1b1c94ee3356/` (not committed).
Scheduled workflow uploads video; manual workflow uploads a different PNG.
Fake Meta downloaded 340925 and 11166 bytes respectively. Their SHA-256 values
matched their respective authenticated review previews and differed across the
two packages, so reusing the previous package's artifact cannot pass. Each
invocation cleans its stack after collecting evidence.

Full ops suite exposed an untouched Windows newline assumption:
`test_restore_relocates_firebase_credentials` expects LF where Windows writes CRLF
(137 passed, 40 skipped, 1 failed at that run). No backup behavior was changed.
An initial highly parallel web run had one existing ReviewFlow timing failure;
the focused rerun and complete two-worker rerun passed. Python suites must run
separately as CI does: collecting all packages together clashes on existing
duplicate `test_health.py` module names.

The two acceptance cases reload the page before upload, preserving the real
session cookie while independently acquiring current upload limits. Continuous
SPA stale-package-limit recovery after publication is not covered; server 409
protection against writing a previous package remains intact.

## Final independent review

Two read-only reviewers checked standards and spec coverage against
`8276eef...dbc3f0b`.

- **Standards:** no Critical/Important findings initially; one artifact-exclusion
  finding was promoted from Minor because cancellation could upload still-usable
  synthetic pairing codes. Recursive seed exclusion now has a RED-to-GREEN CI
  guard test.
- **Spec:** one Important finding fixed: identical media in both cases could mask
  cross-package artifact reuse. A real deployed RED run failed on equal digests;
  different manual media then passed with distinct digests and both normal
  publication workflows intact.
- **Final affected verification:** 58 acceptance/workflow checks passed, one
  existing platform skip; deployed suite 2 passed, no skipped/flaky/unexpected
  cases. Previously completed unaffected suites were not repeated after restart.

### Decisions and limits

- Work remained on the approved current branch, without worktree isolation.
  PowerShell/native tools replaced Bash bookkeeping; no Bash helper execution
  evidence is claimed.
- Runner integration verification extended into browser implementation because
  production startup alone could not demonstrate the requested workflow.
- A minimal dashboard manual-review action was necessary because only its API
  existed. Cost: a small production UI addition, covered by two unit tests.
- Worker progress is observed through a read-only fixture mount because dashboard
  omits tick timestamps. Cost: an extra test-only observation route.
- Each run owns a unique artifact subdirectory to reject stale reports. Cost:
  nested paths, including the recursive seed exclusion.
- Each case reloads its page, retaining the real session cookie. Continuous-SPA
  stale-upload-limit recovery remains outside this acceptance coverage.
- Real authorization/delivery, Android UI, public DNS/certificate issuance,
  provider-failure/recovery combinations and broader dashboard redesign remain
  outside this slice. Existing suites cover broader application behavior; these
  acceptance results do not establish real external-provider delivery.
- No new abstraction was introduced for small fixture dictionaries, composition
  constructors or browser helpers. Hypothetical Compose drift and exotic malformed
  internal responses were not used to expand the fixed harness scope. Manually
  created browser contexts were verified to retain Playwright trace recording.
- Abrupt host termination/forced CI cancellation is outside ordinary cleanup's
  guarantee; orphaned test resources can require operator cleanup. Recursive seed
  exclusion still protects uploaded diagnostics on cancellation.
- Synthetic credentials in private traces remain documented diagnostic sensitivity,
  not evidence of production-secret exposure. Existing Windows newline and web
  timing failures were reported rather than silently changed.

### Deferred minor

Fixture evidence retrieval currently executes through the backend container.
If backend startup fails while fixtures remain available, fixture evidence cannot
be collected through that path; Compose logs/status are still attempted. A future
diagnostic-only improvement can fetch evidence from the fixture container itself.
