# Manual encrypted backup and restore (#23)

`ops/backup.py` is an operator CLI, not a scheduled job or application feature.
It backs up the application PostgreSQL database, production settings and secrets,
current digest-pinned release bundle, and the entire media volume in one age-encrypted
archive. Move completed archives off-server yourself.

## Prerequisites and limits

- Linux, Python 3.12+, Docker/Compose with `--wait`, official `age` and `age-keygen`.
- A healthy **recorded** installation following [deployment.md](deployment.md).
  Source-checkout installations must adopt a baseline first.
- Access to the recorded backend/worker/gateway images and the **exact database
  image** used for the backup. The configured PostgreSQL image/tag must resolve to
  that image before restore. Retain its registry digest or offline image separately;
  archives do not include image layers and are not air-gapped machine backups.
- Existing-target restore retains application database/role and volume identities.
  It does not restore cluster roles, unrelated databases, or external reverse-proxy
  configuration. Caddy regenerates its TLS cache; Android signing keys are separate.
- Unset shell variables interpolated by Compose: recovery uses the production env
  file, not shell overrides. Do not run another initializer or write directly to
  database/media during the maintenance window.
- Allow private disk headroom: conservative preflight reserves four times database
  plus media size for capture, with an additional 64 MiB margin. Restore also needs
  decrypted staging and a complete safety backup. Large archives need substantial
  space; insufficient-space errors must be fixed before retrying.
- Backend and every worker replica stop during capture. Expect unavailable API/media
  requests. A backup restarts original replica counts and verifies service/public
  health. Fresh recovery starts one backend/worker; existing restore preserves counts.

Only native age keys are supported for this workflow. Keep the private identity
offline and outside the installation root; the public recipient suffices for backup.
Never commit keys, environment files, dumps, or archives. Staging is plaintext in a
0700 directory; secrets/archives are 0600. Cleanup unlinks plaintext but does not
guarantee secure erasure. Use trusted storage and encryption at rest if required.

**Only restore archives from a trusted source.** age detects ciphertext tampering and
wrong keys, but public-key encryption does not authenticate who created a new
archive. PostgreSQL restores execute code chosen by the dump's source superuser;
checksums and encryption do not make an untrusted dump safe.

## One-time key preparation

On a trusted operator machine, create a new identity without overwriting an existing
key and keep an offline copy:

```bash
age-keygen -o /safe/dojo-identity.txt
age-keygen -y /safe/dojo-identity.txt
```

The second command displays the public recipient (`age1...`), not the private key.
Copy only that recipient to the VPS. Losing the identity makes backups unrecoverable.
Do not leave the only identity copy on the server you are backing up.

## Backup

Replace paths and recipient; output directory must already exist. Output must be a
new file outside media and must not traverse symlinks:

```bash
python3 ops/backup.py backup --root /srv/aisomedo \
  --recipient age1YOUR_PUBLIC_RECIPIENT \
  --output /private-backups/dojo-20261014.tar.age
```

Success means archive creation and application restart/health succeeded. Failure can
leave a complete encrypted archive if only restart failed; inspect service health
before retrying. Never assume an existing output will be replaced: use a new name.
Copy the encrypted file off-server and retain its checksum with your own custody
records. Periodically prove recovery on a separate test host.

## Existing-installation restore — destructive

This **replaces the selected application database, configuration, and all media**.
Files created after the backup are removed, not merged. Use a maintenance window and
an archive whose source you trust. Never use this as a casual production test.

```bash
python3 ops/backup.py restore --root /srv/aisomedo \
  --archive /private-backups/dojo-20261014.tar.age \
  --identity /safe/dojo-identity.txt \
  --safety-recipient age1YOUR_PUBLIC_RECIPIENT \
  --safety-output /private-backups/before-restore-20261014.tar.age \
  --confirm-replace
```

The original archive is decrypted and checked before mutation. A safety archive must
complete while writers remain stopped before replacement starts. Archive checks
reject unsupported versions, missing/extra members, unsafe paths, links, corrupt
contents, incompatible images and changed storage identities. Firebase credentials
are relocated into `config/firebase.json`; only their host-path env setting changes.

The CLI verifies schema version, table row counts, full media inventory/checksums,
container health and public HTTPS readiness. It does not run migrations during
restore. Row counts are not a semantic checksum of every database value; disposable
round-trip tests additionally check distinctive original data values.

## Fresh-host recovery and failed restore

Prepare the recorded image versions and DNS/TLS or upstream-proxy prerequisites on
the new host. Create an empty real installation directory. There must be **no existing
containers or volumes for `dojo-prod`**: a new directory on the same occupied host is
not a fresh target. Run restore with root/archive/identity/confirmation; omit safety
options because this target has no previous application data.

Once replacement starts, any failure or handled signal leaves application writers
stopped, or reports that stopping itself failed and requires operator intervention.
Do not manually restart against partially restored data. Preserve the original and
safety archives and recover them on a fresh target using the procedure above. Do not
delete live volumes to make a failing target look empty.

SIGINT, SIGTERM and SIGHUP use these recovery rules. SIGKILL/power loss cannot execute
cleanup: inspect application state, keep writers stopped, and preserve archives.
Stale `.dojo-backup-*`/`.dojo-restore-*` directories may contain plaintext; only remove
the exact stale directory after confirming no operation owns it and recovery is safe.
Never use broad wildcard deletion or `docker compose down -v` on production.

## Safe verification

See the [Turkish PowerShell/browser guide](../rehberler/issue-23-yedekleme-geri-yukleme-deneme-rehberi.md).
Integration tests use random `verifybackup...` projects and synthetic data, never
operator credentials. Build verification images as described in the guide and run
on Linux with `REQUIRE_BACKUP_INTEGRATION=1` and matching `VERIFY_IMAGE_TAG`; missing
prerequisites fail instead of silently skipping. Tests remove only their own projects.

Actual evidence and environment limitations belong in
`docs/verification/issue-23-backup-restore.md`. No production backup/restore was run
as part of implementation.

References: [age](https://github.com/FiloSottile/age),
[PostgreSQL 18 pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html).
