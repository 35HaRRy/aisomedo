# Manual encrypted backup and restore — issue #23

## Intent and approved scope

Provide manual Linux VPS recovery commands that produce one encrypted archive
containing PostgreSQL, configuration metadata and secrets, and all media.
Operators move archives off-server themselves. No scheduling, application UI,
cloud transfer, or backup-download endpoint is included.

The operator approved a maintenance window during backup and explicit confirmation
before restore replaces data. The operator also approved Python orchestration with
age encryption, reuse of deployment helpers, an encrypted safety backup before
replacement, validation before mutation, and leaving services stopped on failed
restore rather than exposing partially restored state.

This targets recorded installations described in `docs/ops/deployment.md`:
`config/production.env`, `current.json`, and digest-pinned release bundles under
`releases/<sha>/`. Source-checkout installations must first record their baseline
using the existing deployment adoption procedure. Issue #21 is closed.

## Approach and boundaries

Create `ops/backup.py`, a Python 3.12+ command-line tool for Linux. Reuse
`ops/deploy.py` subprocess handling, installation lock, Compose command construction,
release validation, and health verification. Do not introduce a daemon, custom
cryptography, a new Python dependency, or unrelated deployment refactoring.

Host prerequisites are Docker with Compose, Python 3.12+, and the official age CLI.
Use native age public-key recipients and identity files; passphrases, SSH keys,
plugins, and automatic key management are outside this first version. Operators
generate keys with `age-keygen`, retain the private identity off-server, and supply
only a public recipient when making backups. Never archive encryption identities.

Alternative approaches considered: GPG adds keyring management; custom encryption
adds avoidable security responsibility. age supplies authenticated streaming
encryption and detects wrong keys, changed ciphertext, and truncation.

## CLI contract

Commands, run from the repository or an operator-managed copy of the ops scripts:

```bash
python3 ops/backup.py backup --root /srv/aisomedo \
  --recipient age1... --output /safe/dojo-backup.tar.age

python3 ops/backup.py restore --root /srv/aisomedo \
  --archive /safe/dojo-backup.tar.age --identity /safe/restore-key.txt \
  --safety-recipient age1... --safety-output /safe/before-restore.tar.age \
  --confirm-replace
```

Backup requires a healthy recorded installation. Restore supports that existing
installation or a new, empty, real installation directory. Replacement requires
`--confirm-replace`; existing installations also require both safety options. A
fresh target has no existing application data to back up and does not require
safety options, but must not silently adopt existing Docker volumes or containers.
The CLI refuses ambiguous or partially configured targets rather than guessing.

Outputs must be new regular files, never overwrite existing paths, and must be
outside the media being backed up. Validate prerequisites, arguments, paths, and
available space before stopping services. Failures return nonzero with step labels
and recovery guidance, not secrets, environment contents, or raw command output.

## Archive contents and format

A versioned manifest describes the archive format, creation time, release SHA,
deployment mode, monitoring flag, public origin, database image identity/major
version, and file sizes and SHA-256 checksums.

Include:

- A PostgreSQL custom-format logical dump of the application database, not a copy
  of live database files. Restore ownership to the configured application role;
  do not import cluster-wide roles or unrelated databases.
- Exact production environment file, `current.json`, and the current validated
  release bundle, including Compose overrides and image digest metadata.
- The regular Firebase credential file referenced by rendered Compose configuration
  when monitoring is enabled. Record its archive mapping. On restore, install it
  under the target's private configuration directory and update only its host-path
  setting in the restored environment file so a new root works.
- Every regular file and directory in the complete media volume, including originals,
  upload staging, branding assets, rendered revisions, and retained package media.

Resolve database and media resources from rendered Compose configuration and
container inspection; do not guess host volume paths. Refuse unexpected mounts,
links, or unsupported file types instead of following them outside the selected
resources. The manifest records database table row counts and schema migration
version for post-restore checks. Archive structure and member names are fixed and
versioned; unknown versions are rejected.

Exclude old release bundles, deployment snapshots, logs, Docker image layers,
worker heartbeat records, encryption keys, and Caddy's regenerable TLS cache.
External reverse-proxy configuration and Android signing keys remain separate
operator responsibilities. Restore requires access to the recorded container images
and PostgreSQL-compatible tooling; this is not an air-gapped host image backup.

## Backup sequence

1. Acquire the existing installation lock, shared with manual and automated deploys.
2. Validate release/configuration, healthy containers, storage identities, encryption
   recipient, output location, tools, and disk headroom. Use private temporary
   storage; reserve sufficient space for dump, archive, and encryption output.
3. Stop every backend and worker replica and verify all application writers stopped.
   Prevent concurrent init work; an active initializer makes the operation fail.
4. Capture the logical dump, row-count/schema verification data, configuration,
   release bundle, and complete media while writers remain stopped.
5. Build the manifest and archive, encrypt into a private temporary output, and
   publish the final output only after successful encryption and durable file flush.
   Publication must not overwrite a file created concurrently.
6. Restart the original application services without running schema migrations;
   preserve the original worker replica count and verify health.

The backup command attempts service recovery on any failure or handled interrupt,
including partial stop failures. Report recovery failure separately. Remove private
staging and unfinished output on exit. Never report backup success when application
restart or verification failed, even if an encrypted archive was created.

## Restore sequence

1. Require replacement confirmation, acquire the installation lock, and decrypt
   fully into private staging. Do not modify destination configuration, database,
   media, or running services until decryption and validation finish.
2. Validate manifest types/version, checksums, exact archive inventory, release
   metadata, PostgreSQL compatibility, and dump readability. Reject absolute paths,
   traversal, duplicates, links, special files, and unlisted members. Apply safe
   extraction and space checks; never trust archived permissions or ownership.
3. Preflight required image availability and the prospective Compose configuration.
   For existing installations, stop all writers and create the required encrypted
   safety backup before any destructive change. Keep writers stopped between safety
   capture and replacement. If safety capture fails before mutation, recover the
   original services and abort replacement.
4. Restore the configuration and release bundle into the installation root. A
   fresh root starts its database with the recorded compatible PostgreSQL image.
   Existing database image/storage mismatches must fail before destructive changes.
5. Replace only the selected application database and complete media contents; no
   unrelated database, filesystem path, volume, or Docker project may be touched.
   Replace media rather than merge it, so files created after backup disappear.
6. Verify restored database schema version and table row counts, and exact media
   file inventory/checksums. Start the recorded application release without running
   migrations; check backend, worker, gateway, and public HTTPS health.

After destructive work begins, any error or interrupt stops all application writers
and leaves them stopped. Report the failed step and safety archive location with
manual recovery instructions. No automatic rollback loop or unsafe restart against
partial data. Only a fully verified restore returns success. State/configuration
files alone must not be presented as proof that restore succeeded.

SIGINT, SIGTERM, and SIGHUP follow the recovery rules above. SIGKILL and power loss
cannot run cleanup; the runbook explains private staging cleanup and recovery from
the original or safety archive. Private staging is plaintext: use trusted private
host storage and document that unlinking is not guaranteed secure erasure.

## Security and operating constraints

- Installation and temporary directories use mode 0700; configuration, dumps,
  archives, and restored secret files use mode 0600.
- No production credentials in process arguments, logs, tests, or Git. Private age
  identities are referenced by path, never printed or copied into archives.
- Check links and containment at filesystem trust boundaries. Archive extraction
  must not depend on permissive defaults of tar libraries.
- Explicit confirmation authorizes the CLI's selected restore target only. Tests
  never execute restore against production resources or operator secrets.
- No claims of zero downtime, cluster-wide PostgreSQL recovery, or guaranteed
  secure erasure. Database/media consistency depends on stopping application writers
  and preventing external modifications during the maintenance window.

## Verification and deliverables

Add focused tests in `ops/tests/test_backup.py` using the existing test stack.
Cover format/inventory/checksum validation; wrong identities and tampered/truncated
ciphertext with real age; malicious archive members; configuration/credential path
relocation; lock contention; all-replica quiescing; non-overwriting output; safety
backup failure; interrupted backup recovery; and interrupted restore staying stopped.

Add disposable Linux Docker integration verification in
`ops/tests/test_backup_integration.py`. Seed distinctive database values, environment
settings, nested/binary media, and optional Firebase credentials; back up, change
them, and restore. Assert exact database values, configuration, complete media
contents (including removal of post-backup files), preserved credentials, and healthy
services. Verify fresh-root recovery too. Use random non-production project names
and fixture credentials, following existing deployment integration conventions.
Integration-required mode fails rather than skips when prerequisites are absent.

Document commands, age key custody, maintenance window, disk requirements,
off-server transfer, fresh-host prerequisites, destructive replacement, and failed
restore recovery in `docs/ops/backup.md`, linked from deployment documentation.
Record actual verification results separately; unrun Linux tests are not evidence
that restore was verified. Run relevant type/lint checks, focused tests regularly,
and the full existing suite once at the end. Review changes and commit implementation
to the current branch as requested by the implement skill.

## Approval handoff

The in-chat design is approved. This written specification still needs operator
review before an implementation plan is written. Implementation starts only after
plan review and execution-method selection.

## References

- Issue: https://github.com/35HaRRy/aisomedo/issues/23
- Deployment contract: `docs/ops/deployment.md`, `ops/deploy.py`
- Official age documentation: https://github.com/FiloSottile/age/blob/main/README.md
- Official age authenticated-stream behavior: https://github.com/FiloSottile/age/blob/main/internal/stream/stream.go

age CLI and authentication behavior were checked against current Context7
documentation on 2026-10-14.
