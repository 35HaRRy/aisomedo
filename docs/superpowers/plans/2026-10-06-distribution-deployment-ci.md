# Distribution, Deployment Safety, and Full CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement #39: signed Android Releases, complete merge-gating CI, and rollback-capable main deployments.

**Architecture:** Reuse existing workflows, production Compose, health probes, and `dojo.schema`. A standard-library Python deployment CLI creates digest-pinned release bundles and orchestrates snapshot, isolated migration rehearsal, rollout, and rollback on the VPS. GitHub Actions delivers bundles through native SSH/SCP; Android tags have a separate signing workflow.

**Tech Stack:** Python 3.12+, Bash/OpenSSH, Docker Compose v2, PostgreSQL 16, GHCR, GitHub Actions, existing Gradle/Android tooling.

**Spec:** `docs/superpowers/specs/2026-10-06-distribution-deployment-ci-design.md`

## Global Constraints

- Keep project name `dojo-prod` and all existing persistent volume identities.
- Reuse both proxy modes and optional monitoring; do not change development Compose behavior.
- Deploy exact checked main commits using recorded registry digests, not mutable `latest` tags.
- Never publish or deploy pull-request code with production credentials.
- Preserve snapshots and prior releases; never automatically restore/downgrade the live DB or remove production volumes.
- Automatic migrations must be expand-only and compatible with previous containers; semantic compatibility needs review beyond readiness smoke tests.
- Single-VPS deployment permits downtime; no zero-downtime promise.
- Require real FFmpeg checks, fail-closed signing, strict SSH host-key checking, and serialized deployment without cancelling an active run.
- No production deployment, secrets provisioning, remote rules changes, or new product dependencies during implementation.

## Review Focus

1. Invalid release metadata, shell metacharacters, and escaping paths must fail before service interruption; pin in Task 3.
2. Partial stop, interrupted commands, and snapshot failure must restart previous services and retain current state; pin in Task 3.
3. Recursive schemas and request/response compatibility have different directions; changed constraints cannot silently pass; pin in Task 1.
4. A skipped/failed suite or merge-queue event must never produce a green aggregate/deploy; pin in Task 5.
5. A debug APK, wrong tag/version, or missing keystore must never become a published signed release; pin in Task 2.

## File Map

- `backend/scripts/check_openapi_compat.py`: deterministic, schema-aware compatibility CLI.
- `backend/tests/test_openapi_compat.py`: additive/breaking contract examples and recursion.
- `android/app/build.gradle.kts`: environment-driven release signing and tag/version validation.
- `.github/workflows/android-release.yml`: protected signed APK publication.
- `ops/deploy.py`: bundle, validate, adopt, deploy commands; no generic deployment framework.
- `ops/tests/test_deploy.py`: bundle validation and command-order/failure tests.
- `ops/tests/test_deploy_integration.py`: disposable real Docker/PostgreSQL rollback and persistence test.
- `ops/tests/test_workflows.py`: CI aggregate, trust-boundary, and signing workflow checks.
- `ops/docker-compose.prod.yml`, `ops/.env.example`: Android compatibility settings passthrough.
- `.github/workflows/ci.yml`: complete checks, aggregate status, exact-commit image publication and SSH deployment.
- `docs/ops/deployment.md`, `docs/ops/releases.md`: setup, baseline adoption, signing, and recovery.

## Task 1: OpenAPI backward-compatibility gate

**Files:** Create `backend/scripts/check_openapi_compat.py` and `backend/tests/test_openapi_compat.py`.

**Interfaces:** `breaking_changes(previous: dict, current: dict) -> list[str]`; CLI `python backend/scripts/check_openapi_compat.py BASE.json CURRENT.json` returns 0 for compatible, 1 for breaking, and nonzero for invalid/unsupported input. Task 5 invokes this CLI; no network calls or third-party schema package.

- [ ] Write parameterized tests asserting optional request fields/new operations pass; operation removal, request-required additions, parameter removal/type change, and response property/status removal fail.
- [ ] Add tests for local `$ref` cycles, arrays, nullable/union branches, enum widening/narrowing in request versus response direction, numeric/string bounds, additionalProperties, media types, and security requirements. Reject unsupported structural keywords rather than report an unproven green result; descriptions/examples changes pass.
- [ ] Run `uv run --project backend pytest backend/tests/test_openapi_compat.py -v`; confirm missing implementation fails.
- [ ] Implement recursive compatibility comparison with visited reference pairs and precise JSON-path diagnostics. Resolve request and response references using each document's components; inspect existing operation parameters, request bodies, responses, and reachable schemas. Do not compare documentation-only metadata.
- [ ] Run the new tests and `uv run --project backend ruff check backend/scripts/check_openapi_compat.py backend/tests/test_openapi_compat.py`; expect pass. Check the committed contract against itself: zero changes.
- [ ] Commit only this task's files: `feat(contract): reject breaking OpenAPI changes`.

## Task 2: Signed Android distribution

**Files:** Modify `android/app/build.gradle.kts`, `ops/docker-compose.prod.yml`, `ops/.env.example`; create `.github/workflows/android-release.yml` and signing-related cases in `ops/tests/test_workflows.py`; create initial `docs/ops/releases.md`.

**Interfaces:** Signing environment inputs: `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Optional `ANDROID_RELEASE_VERSION` must equal configured versionName. Workflow tag pattern `android-v*`; output `aisomedo.apk` and `aisomedo.apk.sha256`. Task 5 uses workflow tests; deploy does not publish APKs.

- [ ] Add checks that release tasks with missing/partial signing inputs fail, debug tasks remain usable without secrets, and mismatched release version fails. Pin `assembleRelease` signing configuration and signature-verification-before-upload order in workflow tests.
- [ ] Run new workflow tests before implementation; confirm missing workflow fails. On an Android-capable environment run unsigned `:app:assembleRelease` and require a clear missing-signing-input error, not success/debug fallback.
- [ ] Add release-only validation/signing using environment providers. Keep current source-controlled versionCode/versionName; do not derive versions from CI run numbers. Do not validate secrets eagerly during unrelated debug tasks.
- [ ] Implement tag-triggered workflow using existing Java 25, SDK 35/build-tools 35.0.0 and Gradle wrapper. Decode `ANDROID_KEYSTORE_BASE64` to a private runner temporary file, build/test/lint release, verify with `apksigner`, calculate SHA-256, create a draft Release, attach artifacts, then publish. Clean key files on all exits and avoid tracing secret commands; use `android-release` environment and job-scoped `contents: write`.
- [ ] Forward `ANDROID_CURRENT_VERSION_CODE`, `ANDROID_MIN_VERSION_CODE`, `ANDROID_UPDATE_URL` into production backend without introducing a new minimum-version policy. Add rendered Compose assertions for operator overrides.
- [ ] Document protected signing secrets, tag/version agreement, increasing versionCode, safe key backup, and stable APK URL. Verify tests and debug build remain green. If toolchain available, use a temporary synthetic key to build/verify release locally; never use or invent production credentials.
- [ ] Commit: `feat(android): publish verified signed APKs`.

## Task 3: Digest-pinned deployment transaction

**Files:** Create `ops/deploy.py`, `ops/tests/test_deploy.py`; extend `docs/ops/deployment.md`.

**Interfaces:** Standard-library functions:

- `build_bundle(sha: str, images: dict[str, str], output: Path) -> Path`
- `validate_bundle(path: Path) -> dict[str, str]`
- `adopt_baseline(release: Path, root: Path, *, mode: str, monitoring: bool, origin: str) -> None`
- `deploy(release: Path, root: Path, *, mode: str, monitoring: bool, origin: str, health_timeout: int = 180) -> None`
- `verify_public_health(origin: str, timeout: int) -> None`: bounded HTTPS checks; integration tests replace only this external-network boundary.

CLI subcommands `bundle`, `validate`, `adopt`, `deploy` mirror these functions. Bundle inputs `--sha`, `--backend`, `--worker`, `--gateway`, `--output`; adopt/deploy inputs `--release`, `--root`, `--mode dedicated|existing-proxy`, optional `--monitoring`, and required HTTPS `--origin`. Production project is fixed module constant `PROJECT = "dojo-prod"`; isolated tests override it inside their process only.

**Bundle/state format:** Bundle has `release.json` (`sha`, `images` with exactly backend/worker/gateway), `images.json` (Compose override pinning backend/init/worker/gateway), matching four production Compose files, and `deploy.py`. Require lowercase 40-character commit and `ghcr.io/...@sha256:<64 lowercase hex>` images. Use `<root>/config/production.env`, `<root>/releases/<sha>/`, `<root>/snapshots/`, `<root>/current.json`, and `<root>/deploy.lock`. Current state records successful sha/mode/monitoring/origin, replaced atomically only on success. Snapshot names include UTC timestamp and candidate sha; directory mode 0700/files 0600.

- [ ] Write tests for invalid sha/digests, unexpected metadata/services, missing bundle files, escaping paths, missing/unhealthy baseline, and adoption whose running image IDs do not match the bundle. No stop/migrate command may occur in these cases.
- [ ] Write command-recording tests proving pull → quiesce → dump → isolated restore/rehearsal → previous backend smoke → live init → health → current-state update. Failure at each boundary must retain old state and restore old services if interruption began.
- [ ] Add failure tests for partial stop, snapshot empty/nonzero, clone restore/migration failure, candidate health failure, previous-health failure, and lock contention. Signals must trigger bounded recovery where catchable; SIGKILL/host loss remains manual recovery with preserved state/snapshot.
- [ ] Run `uv run --project backend pytest ops/tests/test_deploy.py -v`; confirm failure before writing the CLI.
- [ ] Implement subprocess argument lists, not shell/eval/source; validate metadata and trusted installation paths before commands. Preserve matching Compose files with each release; reject overwriting a different existing bundle. Use Linux `fcntl.flock` and handling for INT/TERM/HUP; make recovery idempotent, preserve original error, and surface rollback errors separately.
- [ ] Capture rendered Compose configuration privately to obtain DB settings; never print it or read real developer env files in tests. Validate supported CLI/features, origin, existing healthy services, and snapshot headroom (at least twice DB size plus 1 GiB) before stopping. Pre-pull candidate digests and verify prior images locally available.
- [ ] Quiesce only backend/worker; verify they stopped. Execute `pg_dump --format=custom` in existing DB container. Preflight uses a unique temporary network and PostgreSQL 16 container, no published ports/production media, generated credential, bounded readiness, `pg_restore --exit-on-error`, candidate `python -m dojo.schema`, and previous backend `/ready` against the copy. Do not start worker or allow external integrations in rehearsal.
- [ ] Run live init with candidate Compose `run --rm --no-deps init`. Start only backend/worker/gateway with `up --no-build --pull never --no-deps --wait --wait-timeout 180`; do not restart DB or rerun old init during rollback. Probe HTTPS `/ready` JSON status and `/web-health.txt` with certificate validation and bounded retries. Recover using prior bundle/mode/monitoring; clean only named ephemeral resources, retain snapshots and failed bundle.
- [ ] Implement `adopt` as explicit verified bookkeeping for an already-running baseline; no automatic fresh deployment when state missing. Document downtime, migration review, commands, private registry login, disk/retention management, and manual recovery after abrupt interruption.
- [ ] Run CLI help, unit tests, ruff, and `python -m py_compile ops/deploy.py`; expect pass. Commit: `feat(ops): add snapshot preflight and rollback`.

## Task 4: Real deployment failure and persistence verification

**Files:** Create `ops/tests/test_deploy_integration.py`; extend `ops/tests/test_deploy.py` if real execution reveals missing failure coverage.

**Interfaces:** Test imports Task 3 CLI module and overrides `PROJECT` to a unique `verifydeploy...` value. Use already-built `dojo-*-verify:<sha>` images resolved to immutable image IDs. Keep syntactically valid GHCR digests in the test manifests; a test-only subprocess wrapper maps those digest arguments/Compose image overrides to local image IDs, without replacing real dump, restore, migration, health, or rollout commands. Production digest validation stays intact. No real environment/hostname/volume is read or addressed.

- [ ] Write Linux/Docker integration test building old/candidate bundles from the current source, injecting a candidate backend health failure through a test-only bundle override after production bundle validation. Seed DB row and media-file sentinels; record prior image IDs and state.
- [ ] Assert preflight restored sentinel, candidate schema initialization succeeded on clone, failed rollout returns nonzero, previous service image IDs/health recover, DB/media sentinels remain, current sha unchanged, and retained snapshot can be restored independently.
- [ ] Add preflight-failure case proving no production schema mutation or candidate rollout. Test monitoring disabled with no credentials, and render both proxy modes plus monitoring with synthetic credentials. Real public TLS is not available locally: patch only `verify_public_health` for the external HTTP result, retaining real container-health and rollback operations.
- [ ] Run `uv run --project backend pytest ops/tests/test_deploy_integration.py -v`; establish failure without working orchestration. CI environment flag `REQUIRE_DEPLOY_INTEGRATION=1` makes missing Docker/Linux/images fail rather than skip; normal unsupported local hosts may skip explicitly.
- [ ] Resolve only demonstrated gaps in CLI/fixtures, then rerun. Cleanup verifies project prefix and removes only test-owned resources; never execute production `down -v`. Record retained artifacts temporarily before cleanup.
- [ ] Commit: `test(ops): prove rollback preserves persisted state`.

## Task 5: Complete CI, image publishing, and SSH automation

**Files:** Modify `.github/workflows/ci.yml`; extend `ops/tests/test_workflows.py`, `docs/ops/deployment.md`, `docs/ops/releases.md`.

**Interfaces:** Task 1 compatibility CLI; Task 3 bundle/deploy CLI; Task 4 Docker verification. GitHub production variables `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_ROOT`, `DEPLOY_MODE`, `DEPLOY_ORIGIN`, `DEPLOY_MONITORING`; secrets `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`. Registry names: lowercase `ghcr.io/<owner>/aisomedo-backend`, `aisomedo-worker`, `aisomedo-gateway`.

- [ ] Write workflow checks for `push`/`pull_request`/`merge_group`, aggregate `required` depending on every test/build job with `always()` and exact-success evaluation, main-only publication/deployment, least-privilege tokens, environment selection, concurrency with `cancel-in-progress: false`, host-key checking, and no PR secrets. Use existing libraries/stdlib; avoid adding YAML dependency solely for tests.
- [ ] Run `uv run --project backend pytest ops/tests/test_workflows.py -v`; confirm absent gates/publication fail.
- [ ] Preserve existing suites; add host FFmpeg/ffprobe installation for Python tests and dedicated real FFmpeg fixture job with Docker/tool availability assertions and zero skipped required fixtures. Run schema/deploy checks and real deployment fixture in ops after building named verification images; retain Caddy validation and monitoring renders.
- [ ] In contract job fetch full base history, regenerate schema/clients, enforce drift, compare PR base / merge-queue base / preceding main commit with Task 1 CLI. Missing required baseline fails clearly, not silent pass; first repository commit uses an explicit documented bootstrap exception.
- [ ] Add aggregate `required` only for checks, then main-only publishing needing its success. Build each checked commit's backend/worker/gateway image using Buildx; tag full SHA, push with `packages: write`, capture immutable digest outputs, and invoke Task 3 bundle creation. Upload only release bundle as workflow artifact; no secrets/config env included.
- [ ] Add `production` deployment job needing publication, serialize production with no active cancellation, download matching bundle, validate inputs, and install SSH key/verified known_hosts at restrictive permissions. SCP to unique staged directory under root; invoke remote deploy with arguments validated before interpolation. Never run `ssh-keyscan` as unattended trust establishment or use `StrictHostKeyChecking=no`. Use `--no-build`; GHCR auth is host-provisioned.
- [ ] Document operator setup for protected environments, registry read token, SSH account/Docker privilege, host fingerprint verification, production env path, baseline adoption, and main rules requiring `ci / required` (confirm exact UI status context after first hosted run). Do not modify remote rules or deploy automatically from this session.
- [ ] Run all new Python tests, relevant lint, contract regeneration/drift, existing suites, available web/Android checks, Compose renders and real Docker fixture. Separate pass/fail/skipped/unavailable evidence; inspect final diff for secret handling and data-loss paths. Commit: `ci: gate releases and automate safe deployments`.

## Final Review and Handoff

- [ ] Self-review coverage: all #39 acceptance criteria mapped above; operator configuration is explicitly pending, not presented as fulfilled infrastructure.
- [ ] Obtain independent review according to chosen execution method; resolve verified findings and rerun affected checks.
- [ ] Confirm Git status contains only intended changes and report commits plus commands/results.
- [ ] Do not close #39 as fully operational until required repo rules, a real signed APK Release, and hosted SSH deployment/rollback evidence exist; report implementation versus infrastructure verification separately.

## Execution Choice

Recommended: Native execution in this session. Tasks share workflow and bundle interfaces, so inline implementation avoids repeated context setup; one independent whole-branch review remains necessary before completion. Subagent-driven execution remains available if the user prefers per-task independent review.

Written-spec review, implementation-plan review, and inline execution: approved in conversation.
All five tasks implemented; local verification and independent review performed.
Operational acceptance remains pending operator configuration and hosted evidence.
