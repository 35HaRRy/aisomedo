# Deployed-stack Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove one scheduled and one manual publication through the built web application and real deployed services.

**Architecture:** Layer disposable fixture services and test-only composition over production Compose and images. Run Chromium against the built gateway without API interception; control time and external outcomes through fixture services while the ordinary worker loop performs real work.

**Tech Stack:** Existing Python/pytest/httpx/FastAPI, Docker Compose, PostgreSQL 18, FFmpeg, TypeScript/Playwright/Chromium, Caddy.

**Spec:** `docs/superpowers/specs/2026-10-15-deployed-stack-acceptance-design.md`

## Global Constraints

- Use existing publishing clock, notifier, and Meta HTTP adapter seams.
- The runner passes a dedicated environment file explicitly and never reads `ops/.env` or uses `dojo-prod` resources.
- Test controls belong only to fixture services and acceptance bootstrap files; they are not added to the production HTTP API.
- No real Meta/Firebase credentials, production validation bypasses, lifecycle-result SQL seeding, or browser API interception.
- Both cases use real media, rendering, shared volumes, production schema initialization, and the built web gateway.
- Required CI must fail rather than skip when prerequisites or workflows are missing.
- Work stays on the current branch; stage only issue #40 changes.

## Review Focus

- Fake Meta ingestion failure must prevent successful publication; test in Task 1.
- Divergent or malformed fixture time must fail visibly rather than silently use wall time; test in Task 2.
- Missing wiring must not fall back to stub publishing or discard notifications; test in Task 2.
- Partial startup or failed browser execution must retain evidence and clean only owned resources; test in Task 3.
- A passing configuration with zero executed acceptance cases must fail CI; test in Task 5.

## File Map

- `ops/acceptance/fixtures.py`: fixture-only HTTP service: clock, fake Graph API, notification collector, evidence.
- `ops/acceptance/bootstrap.py`: test-only backend/worker composition and operator fixture setup.
- `ops/acceptance/run.py`: disposable stack lifecycle, certificates, browser invocation, evidence and cleanup.
- `ops/acceptance/Dockerfile.browser`: Node 22, existing npm lockfile dependencies, Chromium and certificate trust tools.
- `ops/acceptance/gateway-tls.caddy`: HTTPS front door forwarding to the unchanged production gateway.
- `ops/docker-compose.acceptance.yml`: override plus fixtures, TLS front door, and browser runner.
- `ops/tests/test_acceptance.py`: focused fixture/wiring/runner checks using existing pytest environment.
- `web/playwright.acceptance.config.ts`: deployed-only, serial Chromium configuration, no Vite server.
- `web/acceptance/publication.spec.ts`: two real workflows and shared browser setup/helpers.
- `web/package.json`: separate `test:acceptance` command.
- `.github/workflows/ci.yml`, `ops/tests/test_workflows.py`: required execution, evidence and CI policy checks.
- `docs/verification/issue-40-deployed-stack-acceptance.md`: local command, evidence contract, limitations.

Keep fixture/bootstrap sources mounted read-only into production backend/worker images; do not copy them into production Dockerfiles. The browser-only image is a test tool, not a replacement application image.

### Task 1: Strict External Fixtures

**Files:** Create `ops/acceptance/fixtures.py`; create `ops/tests/test_acceptance.py`.

**Interfaces:** `create_app(*, initial_time: datetime, ca_file: Path) -> FastAPI`; `GET /clock -> {now: ISO8601}`; `POST /clock {now}` advances monotonically; `POST /notifications` accepts serialized Notification and tokens; `GET /evidence` returns clock, containers, publications and notifications. Graph routes use `/v26.0/{id}/media`, `/{container_id}`, and `/{ig_user_id}/media_publish` with the real adapter's request/response shapes.

- [ ] Write tests `test_graph_ingests_before_finished`, `test_graph_rejects_unfetchable_video`, `test_publish_requires_ingested_container`, `test_unknown_graph_request_fails`, `test_clock_requires_aware_monotonic_time`, and `test_collector_preserves_recipients_and_review_data`.
  Assert downloaded SHA-256/caption/byte count are recorded, failed ingestion never returns FINISHED, unknown IDs fail, naive/backward dates return 422, and notification data survives unchanged. Two publish calls must remain observable as two calls, not be concealed by fake deduplication.
- [ ] Run `uv run --project backend pytest ops/tests/test_acceptance.py -v`; confirm missing fixture implementation fails.
- [ ] Implement HTTP fixture using installed FastAPI/httpx and stdlib hashing/locking. Initial clock: `2026-10-19T06:59:00+03:00`; reject malformed controls and unexpected Graph payloads. Fetch signed HTTPS media with explicit CA verification and bounded timeouts before recording ingestion. Keep state per fixture process; evidence excludes access tokens and signed URL queries.
- [ ] Rerun focused tests and `uv run --project backend ruff check ops/acceptance ops/tests/test_acceptance.py`; require zero failures.
- [ ] Commit: `test: add strict publication acceptance fixtures`.

### Task 2: Test-only Backend and Worker Composition

**Files:** Create `ops/acceptance/bootstrap.py`; extend `ops/tests/test_acceptance.py`.

**Interfaces:** `RemoteClock.now() -> datetime`; `CollectorNotifier.send(notification: Notification, tokens: list[str]) -> NotificationResult`; `CollectorNotifier.notify(title: str, body: str) -> None`; `build_publishing() -> DojoPublishing`; `create_backend_app() -> FastAPI`; `main(argv: list[str] | None = None) -> int`, with `backend`, `worker`, and `seed` modes. `seed` emits JSON containing browser/device pairing codes, never a publication result.

- [ ] Write `test_remote_clock_is_shared_and_fails_closed`, `test_collector_failure_is_not_delivery`, `test_bootstrap_uses_real_http_publisher_and_signed_urls`, and `test_worker_bootstrap_preserves_normal_main_loop`. Assert backend/worker clock values match fixture updates and malformed/unavailable clock raises; collector failure reports no successful delivery; HTTP publisher targets fixture host and signed URL store uses HTTPS; worker invokes ordinary `worker.main.main` rather than a replacement scheduling loop.
- [ ] Run the focused file; confirm new tests fail before implementing composition.
- [ ] Construct real PostgresStore-backed facades using existing constructor seams. Use `HttpMetaPublisher(host="http://fixtures:8000")` and real `HmacSignedUrlStore`; supply RemoteClock and CollectorNotifier to both application processes. Use `backend.main.create_app` injections. Wrap worker dependency factories in the acceptance entrypoint, then invoke unmodified worker main; preserve leadership, health, repair and job handling. Do not add production environment switches.
- [ ] Seed consent policy and pairing codes through existing CLI/domain helpers. Establish encrypted synthetic Meta account using existing connection seam and fixture provider, not raw lifecycle rows. Keep that account healthy during worker maintenance through the same synthetic provider. Browser completes actual onboarding, including logo, consent and schedule. Device recipient registration uses normal authenticated API after device pairing.
- [ ] Run focused pytest, Ruff, and `uv run --project backend mypy --follow-imports=silent ops/acceptance`. Fix explicit typing; do not blanket-disable the checker.
- [ ] Commit: `test: wire acceptance dependencies at existing seams`.

### Task 3: Disposable Production-like Runner

**Files:** Create `ops/acceptance/run.py`, `ops/acceptance/Dockerfile.browser`, `ops/acceptance/gateway-tls.caddy`, `ops/docker-compose.acceptance.yml`; extend `ops/tests/test_acceptance.py`.

**Interfaces:** `main(argv: list[str] | None = None) -> int`; CLI `python ops/acceptance/run.py --image-tag TAG --output PATH [--build]`. Default output: `artifacts/acceptance`. Tag identifies `dojo-{backend,worker,gateway}-verify:TAG`; `--build` builds those images from current checkout. Runner passes browser environment `ACCEPTANCE_BASE_URL=https://dojo.acceptance.test`, `ACCEPTANCE_FIXTURES_URL=http://fixtures:8000`, `ACCEPTANCE_SEED_FILE=/evidence/seed.json`.

- [ ] Write runner tests with mocked subprocesses: `test_runner_uses_explicit_synthetic_env_and_unique_project`, `test_partial_startup_still_collects_and_cleans`, `test_browser_failure_preserves_exit_status`, `test_cleanup_failure_is_visible`, and `test_missing_images_fail_without_skip`. Assert cleanup names only the generated project, diagnostics run before cleanup, and failures remain nonzero.
- [ ] Run focused tests and confirm runner-dependent checks fail.
- [ ] Implement runner with subprocess argument arrays, finite command timeouts, `try/finally`, unique project prefix `dojo-acceptance-`, fresh scratch directory, explicit `--env-file`, and production Compose plus acceptance override. Clear conflicting inherited Compose/application variables from subprocess environment. Keep scratch files until services have stopped. Inspect merged config to verify production services and project-scoped volumes.
- [ ] Generate throwaway CA and SAN certificate for `dojo.acceptance.test`. TLS front door uses that certificate and proxies unchanged gateway HTTP. Network alias resolves hostname only inside test network. Python fake trusts CA explicitly; browser runner installs CA into OS and Chromium NSS trust stores. Never use global ignore-HTTPS flags. Preserve production `COOKIE_SECURE=true` and HTTPS URL validation.
- [ ] Add browser tool image using Node 22, `web/package-lock.json`, Playwright Chromium installation and certificate tools. Run browser on Compose network, mounting output and test certificate material; no host ports are needed. Fixtures run from backend image; backend/worker bootstrap and fixture sources are read-only mounts. Override verification image references for init/backend/worker/gateway and shorten worker interval to 1 second.
- [ ] Assert real stack readiness, run seed once, then browser runner; collect bounded logs/status and evidence on failure. Limit evidence directory permissions because seed pairing codes are sensitive even when synthetic. Always remove only invocation-owned containers/volumes/network; expose cleanup failures.
- [ ] Verify unit checks/typechecks and `docker compose ... config --format json` through runner dry preparation tests. Build and start disposable stack; require real `/ready`, built web health asset and trusted HTTPS responses, then cleanup.
- [ ] Commit: `test: run isolated production acceptance stack`.

### Task 4: Two Browser Publication Workflows

**Files:** Create `web/playwright.acceptance.config.ts`, `web/acceptance/publication.spec.ts`; modify `web/package.json`.

**Interfaces:** npm script `test:acceptance` invokes only acceptance config. Config uses one Chromium project, one worker, serial execution, no Vite `webServer`, 180-second per-test bound, retained failure trace/screenshot and JSON report under `/evidence`. Browser helpers remain local to this spec; do not import mocked API fixtures.

- [ ] Write exactly two cases: `scheduled publication preserves reviewed artifact` and `manual publication preserves cadence`. Add explicit public-state, fake-service and video-digest assertions before writing shared setup helpers.
- [ ] Run against stack; confirm failure is missing setup/actions, not test discovery or an unavailable browser.
- [ ] Pair browser using seed code, pair a synthetic Android recipient via normal API and register token, then complete onboarding in UI. Use accessible names from existing components; upload logo and real media fixture `web/e2e/fixtures/timeline.mp4`. Configure Monday `2026-10-19` at `07:00` Istanbul, with initial fixture clock at `06:59`. Enable plan and wait for setup readiness and media finalization.
- [ ] Scheduled case: advance clock to `2026-10-19T07:00:01+03:00` using fixture HTTP, then wait for review and collector record. Play actual preview and obtain full authenticated bytes through browser request context for SHA-256. Approve through existing two-step confirmation UI; wait for confirmed completed package and compare caption/digest with fake Meta. Assert precisely one container creation and one publish for that case.
- [ ] Manual case: upload distinct filename/media into next Aktif Paket before next recurring due time; request manual publication in UI, then perform same review, notification, playable-preview and digest assertions. Compare next regular due time before/after manual publication; it must remain unchanged. Cases track their own folder/review/container identifiers, not global counts alone.
- [ ] Wait for another normal worker turn after each completion and reassert publish count. Use normal public API for observable state checks where UI has no field; use runner's read-only volume inspection for documented `-completed` folder/manifest evidence. No SQL lifecycle assertions or internal-method triggers.
- [ ] Run `npm --prefix web run typecheck`, both acceptance tests and existing `npm --prefix web test` / browser suite. Require both acceptance cases executed and passed, no skips; record real failures before adjusting implementation.
- [ ] Commit: `test: cover scheduled and manual deployed publication`.

### Task 5: Required CI, Documentation, and Final Review

**Files:** Modify `.github/workflows/ci.yml`, `ops/tests/test_workflows.py`; create `docs/verification/issue-40-deployed-stack-acceptance.md`.

**Interfaces:** CI ops job runs `uv run --project backend python ops/acceptance/run.py --image-tag "$GITHUB_SHA" --output artifacts/acceptance` after existing verification image builds. Existing `required` aggregation already depends on ops; retain that dependency. Add always-run artifact upload for acceptance diagnostics, excluding seed codes and private certificate keys.

- [ ] Add workflow tests asserting acceptance invocation follows image builds, is not continue-on-error, and has always-run diagnostics upload. Add runner report test `test_acceptance_requires_two_passed_cases` with absent/empty/skipped/one-case JSON reports; each must return nonzero. Two named passing cases with no failed/retried/skipped cases must succeed.
- [ ] Run focused workflow/runner tests; confirm new policy assertions fail before CI wiring.
- [ ] Implement CI step/report validation and diagnostics upload. Document local `uv run --project backend python ops/acceptance/run.py --image-tag issue40 --build --output artifacts/acceptance`, Docker Linux-container prerequisites, two covered paths, test-only seams, cleanup ownership and artifact locations. Keep existing backend/web/Android checks intact.
- [ ] Run focused typechecks/lint regularly, then final full checks: Python pytest suites for dojo-core/backend/worker/ops; Python mypy for all three source packages plus acceptance files; Ruff for affected Python scopes; web unit/typecheck/build/existing browser suite; Android unit/lint/build checks from existing CI; both real acceptance cases. Ensure required services/media tools exist for relevant tests. Report unavailable checks explicitly, never equate skipped integration with passing acceptance.
- [ ] Self-review plan/spec coverage and staged diff, then invoke code-review skill against implementation baseline. Resolve verified findings and rerun affected checks. Review must cover standards and issue #40 acceptance; do not modify unrelated work.
- [ ] Commit only issue files: `test: require deployed publication acceptance in CI`. Record commit IDs, test evidence, and any remaining environment limits in final handoff. Do not push or close issue automatically.
