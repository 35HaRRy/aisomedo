# Manual Encrypted Backup and Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #23: manually create and restore one encrypted archive containing database, configuration, and all media.

**Architecture:** A Linux CLI in `ops/backup.py` uses age and existing deployment helpers. Backup quiesces all writers; restore validates first, takes an encrypted safety backup before replacement, and keeps writers stopped after destructive failure. Existing disposable Compose test conventions provide real recovery evidence.

**Tech Stack:** Python 3.12+, stdlib, official age CLI, Docker Compose, PostgreSQL, existing pytest/ruff/mypy tooling.

**Spec:** `docs/superpowers/specs/2026-10-14-manual-encrypted-backup-restore-design.md` (operator approved).

## Global Constraints

- Python 3.12+, Linux VPS, recorded installations only; native age recipients and identity files.
- No new Python dependency, custom cryptography, scheduling, application UI, cloud transfer, or backup-download endpoint.
- Installation and temporary directories use mode 0700; configuration, dumps, archives, and restored secret files use mode 0600.
- Reuse deployment helpers and installation lock; production Docker project remains `dojo-prod`.
- Tests never execute restore against production resources or operator secrets.
- Existing-target replacement requires confirmation and a completed encrypted safety backup.
- Failed destructive restore leaves application writers stopped; no automatic rollback loop.
- No image exports, external-proxy configuration, Android signing keys, or Caddy TLS cache in archives.
- Maintain Turkish operator guide with browser/Android observations or PowerShell commands containing no Python or SQL source.
- Commit changes to current branch. Do not push, deploy, or restore production while implementing.

## Review Focus

1. Extra worker replicas and partial stop failures: all writers stop; backup recovery preserves original replica count (Task 2).
2. Different installation root and external Firebase credential path: secret is recovered locally and only its environment path changes (Task 3).
3. Concurrent output creation, low disk space, and media-contained output paths: fail safely without overwriting or unnecessary downtime (Tasks 1–2).
4. Fresh root beside existing project resources: refuse implicit adoption or modification (Task 3).
5. Signals after replacement and failed health probes: stop writers, retain safety archive, and return failure without claiming recovery (Task 3).

## File Map

- Create `ops/backup.py`: CLI, archive validation/encryption, backup and restore orchestration. Keep helpers private except interfaces below; no framework or speculative module split.
- Create `ops/tests/test_backup.py`: focused trust-boundary and failure-path tests; double only external Docker calls where practical.
- Create `ops/tests/test_backup_integration.py`: real age/PostgreSQL/media recovery on disposable Linux Compose projects.
- Modify `.github/workflows/ci.yml`: require age and new tests in existing ops job, reusing verification images.
- Create `docs/ops/backup.md`; link from `docs/ops/deployment.md`.
- Update `docs/rehberler/issue-23-yedekleme-geri-yukleme-deneme-rehberi.md` after implementation with actual test commands/results.
- Create `docs/verification/issue-23-backup-restore.md`: evidence, environment, skips, and remaining limitations.
- Avoid modifying `ops/deploy.py` unless a demonstrated shared-helper defect blocks correct reuse; test all existing callers if changed.

## Task 1: Authenticated archive and safe extraction

**Files:** `ops/backup.py`, `ops/tests/test_backup.py`.

**Interfaces:**
- `encrypt_archive(archive: Path, recipient: str, output: Path) -> None`: publish new encrypted file without overwrite.
- `decrypt_archive(archive: Path, identity: Path, output: Path) -> None`: succeed only after complete authenticated decryption.
- `validate_archive(archive: Path, staging: Path) -> dict`: validate/extract and return versioned manifest.
- Manifest v1 keys: `version`, `created_at`, `state`, `database`, `files`, `credentials`. `state` matches existing current.json fields; `database` includes image identity, major version, table row counts and schema version. `files` maps regular payload paths to size/SHA-256; manifest excludes its own digest. `credentials` maps supported secret name to archived path.
- Fixed payload roots: `database.dump`, `config/production.env`, `current.json`, `release/`, `credentials/`, `media/`; `manifest.json` is metadata. Directory entries preserve empty media directories but cannot escape these roots.

- [ ] Write tests named `test_archive_roundtrip`, `test_unsafe_archive_rejected`, `test_manifest_inventory_and_checksums`, `test_wrong_identity_and_tampered_ciphertext`, `test_output_never_overwritten`, and `test_archive_space_limit`. Assert valid nested/binary/empty-directory media extracts; traversal, absolute names, aliases such as `a/../b`, duplicate names, links, devices, unknown versions, malformed metadata, missing/extra members, oversized declared entries, and bad digests fail before destination mutation. Parameterize ciphertext changes/truncation with real age; required-test mode must fail when age is absent.
- [ ] Run `uv run --project backend pytest ops/tests/test_backup.py -v`; confirm new tests fail because implementation is absent.
- [ ] Implement interfaces with stdlib tar/json/hashlib and official age subprocesses. Fully decrypt before extraction; manually validate normalized POSIX member paths and types. Use private staging, bounded disk-space checks, and exclusive final publication (not overwrite-capable rename). Confirm recipient validity before downtime by encrypting an empty private probe. Do not print identities or subprocess output.
- [ ] Run focused tests and `uv run --project backend ruff check ops/backup.py ops/tests/test_backup.py`. Run `uv run --project backend mypy --follow-imports=silent ops/backup.py` and fix new CLI type errors without broadening repository configuration.
- [ ] Commit only this task's files: `feat(ops): validate encrypted recovery archives`.

## Task 2: Consistent encrypted backup

**Files:** `ops/backup.py`, `ops/tests/test_backup.py`.

**Interfaces:**
- Consume Task 1 encryption/validation and `deploy.installation_lock`, `compose`, `validate_bundle`, `running`, `inspect_container`, `run`, `verify_public_health`.
- `backup(root: Path, recipient: str, output: Path) -> None` owns shared lock and maintenance lifecycle.
- `read_installation(root: Path) -> dict` returns validated `state`, `release`, `images`, `command`, rendered `config`, inspected `containers`, `media_volume`, and `worker_count`.
- `capture_archive(installation: dict, staging: Path) -> Path` requires already quiesced writers; produces Task 1 archive. Restore reuses this helper for safety capture without recursively acquiring lock or restarting services.

- [ ] Write `test_backup_includes_database_config_credentials_and_all_media`, `test_all_writer_replicas_stopped_before_capture`, `test_backup_failure_and_signal_restart_original_replicas`, `test_lock_contention_prevents_mutation`, `test_backup_preflight_before_stop`, and `test_restart_failure_not_success`. Record external command order; verify all backend/worker IDs are stopped, init is not active, gateway is not treated as a writer, replica count survives restart, and failure emits no secrets. Cover low space, missing credential, unsupported mounts, links, output inside media, and concurrently created output.
- [ ] Run focused tests to observe failures for missing backup implementation.
- [ ] Implement healthy-installation discovery from recorded release and rendered Compose; reject unsupported storage/environment combinations. Use inspected db container for custom-format pg_dump and read-only mounting of selected media volume in a disposable helper using existing backend image/Python stdlib, not a new utility image dependency. Record deterministic table identities/counts and schema version while writers are stopped. Capture credential source via Compose's resolved secret mapping, not ad hoc environment parsing.
- [ ] Implement signal-safe stop/capture/encrypt/restart lifecycle: save original handlers, handle SIGINT/SIGTERM/SIGHUP, verify stopped containers, and ignore repeated signals during recovery. Restart with no init/migrations, retain original replica count, check service/public health, and distinguish archive creation from restart success. Clean only resources/staging owned by this invocation.
- [ ] Run `uv run --project backend pytest ops/tests/test_backup.py ops/tests/test_deploy.py -v`, ruff and new-CLI mypy checks from Task 1.
- [ ] Commit: `feat(ops): create consistent encrypted backups`.

## Task 3: Safe restore for existing and fresh targets

**Files:** `ops/backup.py`, `ops/tests/test_backup.py`.

**Interfaces:**
- Consume Tasks 1–2; safety capture calls `capture_archive` within already-held lock and stopped-writer lifecycle.
- `restore(root: Path, archive: Path, identity: Path, *, confirm_replace: bool, safety_recipient: str | None = None, safety_output: Path | None = None) -> None`.
- `main() -> int`: argparse `backup` and `restore` subcommands with exact options in spec; sanitized nonzero failures. Private helpers may be added only to support these concrete flows.

- [ ] Write `test_restore_validation_before_mutation`, `test_restore_requires_confirmation_and_safety_archive`, `test_safety_failure_recovers_original_services`, `test_restore_replaces_not_merges_media`, `test_fresh_target_rejects_existing_resources`, `test_restore_relocates_firebase_credentials`, `test_restore_interrupt_and_health_failure_leave_writers_stopped`, and `test_cli_help_and_error_redaction`. Assert current release/config/database/media are untouched for validation errors; incompatible PostgreSQL image or storage fails before destructive work; ambiguous partial target is refused; only declared secret host path changes on relocation.
- [ ] Run focused tests and observe missing restore/CLI failures.
- [ ] Implement target classification under existing installation lock: empty real root only for fresh recovery, otherwise require complete validated baseline. Reject existing project containers/volumes for fresh recovery; preflight images, prospective environment/Compose and private disk staging before downtime. Do not use a production environment file in tests.
- [ ] On existing target, stop/verify all writers and produce authenticated encrypted safety output before mutation. Restore current bundle/configuration and relocated credential; replace only configured application database with pg_restore exit-on-error/no-owner/no-acl and exact selected media volume contents. No cluster restore or broad volume deletion. Fresh database uses recorded compatible image; active init never runs during restore.
- [ ] Compare schema version/table counts and exact media checksums/inventory before starting recorded app. Start without migrations, verify health, and on any failure after first mutation stop writers and return explicit safety-archive recovery guidance. Keep original services recoverable on pre-mutation failure. Preserve safety archive on success and failure.
- [ ] Run focused backup/deployment tests, ruff, and new-CLI mypy. Invoke help on Linux to check actual argparse options match spec.
- [ ] Commit: `feat(ops): restore encrypted installation backups`.

## Task 4: Real recovery evidence and operator workflow

**Files:** `ops/tests/test_backup_integration.py`, `.github/workflows/ci.yml`, `docs/ops/backup.md`, `docs/ops/deployment.md`, Turkish guide, verification report.

**Interfaces:** Consume CLI APIs and existing `ops/tests/test_deploy_integration.py` verification-image conventions. Set `REQUIRE_BACKUP_INTEGRATION=1` to fail if Linux/Docker/age/verification images are missing; optional local runs skip with explicit reasons. Use `VERIFY_IMAGE_TAG` for prebuilt images.

- [ ] Add real integration tests `test_existing_installation_roundtrip`, `test_fresh_root_roundtrip`, and `test_restore_failure_keeps_writers_stopped`. Use random project names, fixture credentials, generated temporary age keys, original DB row values, nested/binary/empty-directory media and dummy Firebase file. Change DB/config/media after backup, including new extra media file; restore must recover exact original values and remove extra file. Run with two worker replicas and no real publication/notification targets.
- [ ] Run integration-required tests before finalizing harness; record actual failure if CLI/harness is wrong. Reuse digest-to-local-image fixture mapping while preserving production validation rules; never patch validation into unconditional success. Fixture public health uses local HTTP observations, not production DNS or TLS secrets.
- [ ] Extend existing ops CI job: install official age from Ubuntu package, lint new CLI/tests, run focused tests and new-CLI mypy, then required backup integration after existing verification-image builds. Existing deployment integration remains required. Add assertions in existing workflow tests to pin new required integration wiring.
- [ ] Document actual commands, key custody, space/maintenance limits, no-overwrite policy, safety archive, fresh-host requirements, image availability, recovery after interruption, and staging plaintext limitations. Link backup runbook from deployment docs. Update Turkish guide with safe PowerShell `uv` test invocations and optional WSL Linux invocation without embedding Python/SQL code; no live destructive restore command in casual test instructions. Browser/Android checks observe only an isolated restored test installation.
- [ ] Run all affected tests and required Linux round trips. Capture environment/tool versions, commands, pass/fail/skip counts in verification report. If Linux execution is unavailable, record blocker and do not claim issue acceptance or verified restore.
- [ ] Commit: `test(ops): verify encrypted recovery round trips`.

## Final Verification and Review

- [ ] `uv run --project backend ruff check ops/backup.py ops/tests`; new-CLI mypy command from Task 1; existing core/backend/worker type checks from CI.
- [ ] Run full Python suite once at end: `uv run --project backend pytest dojo-core/tests backend/tests worker/tests ops/tests -v` with Linux/media prerequisites and required backup integration enabled. Run existing web `npm test`, `npm run build`, `npm run test:browser` from `web`; Android Gradle test/build/lint/instrumentation compilation from `android`, matching CI. Record environment blockers, never treat skips as verification.
- [ ] Use code-review skill against fixed pre-implementation base SHA; resolve actionable correctness/security findings and rerun affected tests. Preserve unrelated user changes. Confirm no secret material, plaintext backup or private identity is tracked.
- [ ] `git diff --check`, review staged scope, commit remaining own changes, and report commits plus evidence. No push, production deployment, issue closure, or live restore without separate authorization.

## Handoff

Spec and plan approved; native execution selected. Tasks 1–4 implemented on current
`development` branch, followed by independent standards/spec review and tested fixes.
Execution evidence and remaining regression limits:
`docs/verification/issue-23-backup-restore.md`. No merge, push or production restore
was authorized or performed; the unrelated worker timing-test failure remains reported.
