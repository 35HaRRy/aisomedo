# Distribution, deployment safety, and full CI

Issue: #39, part of the Dojo Reel Publishing MVP (#1).

## Intent and approved direction

Publish signed Android APKs through GitHub Releases, prevent merging failed
checks, and automatically deploy checked main commits to one Linux VPS.
The user approved CI-built images in GHCR and SSH-based deployment to the
existing Docker Compose installation. Android distribution remains separate.
No Kubernetes, self-hosted runner, new deployment platform, or public app store.

This document makes that direction concrete. The user approved the written
spec and implementation plan in conversation, choosing inline execution. All five
implementation tasks are now implemented; live deployment requires separate authorization.

## Existing boundaries

Reuse production Compose, both dedicated-domain and existing-proxy overrides,
optional monitoring, the Caddy/web image, PostgreSQL 16, `dojo.schema`, and
existing readiness/worker/web probes. Keep project name `dojo-prod` and all
existing persistent volume identities. Development Compose remains usable.

Backend and worker are separate containers on the same VPS. Web assets remain
inside the Caddy gateway. GHCR stores images; it does not run the applications.
Operator configuration and credentials stay outside release archives.

## Complete CI and merge gate

Run the existing Python lint, type checks, and core/backend/worker tests;
web tests, build, and browser tests; Android unit tests, build, lint, and
instrumentation compilation; generated-contract/client freshness; Compose
validation; and backend/worker/gateway builds. Run real FFmpeg fixtures as an
explicit check, with required tools available: absent Docker or FFmpeg must
fail that check rather than make it succeed through skipped fixtures.

Compare OpenAPI against the pull request base or the preceding main revision.
Reject breaking changes to existing operations and client-visible schemas,
including removed operations/properties, newly required request fields,
narrowed accepted values, changed types, and incompatible response shapes.
Allow additive compatible changes. Keep freshness and Android N/N-1 behavioral
tests; do not mistake regenerating clients for compatibility verification.

Expose one aggregate `required` status that succeeds only when every required
suite succeeds, including on merge-queue checks. Document the repository rule
requiring it on main. Adding a workflow alone cannot enforce branch protection;
remote rules must be configured explicitly by the operator.

## Android release

Use a separate workflow triggered by `android-v*` tags. Build the tagged
source with the existing Gradle wrapper and Android toolchain. Require a
release keystore, alias, and passwords from protected release secrets;
missing signing inputs fail closed, never fall back to debug signing.

Keep versionCode/versionName in the application build configuration; require
the tag version to match versionName and document increasing versionCode for
each Android release. Verify the resulting APK with `apksigner`, then attach
it as `aisomedo.apk` with a SHA-256 checksum to the corresponding GitHub Release.
Restrict release permissions to that job and remove temporary key files.
Never commit keys or log passwords. Signed APK publication needs no VPS SSH.

Pass the existing Android compatibility/update settings through production
Compose so operators can point the app to the published APK and preserve N/N-1
support. Do not raise the minimum Android version merely on a backend deploy.

## Image publishing and SSH transport

Only a successful main CI run can publish backend, worker, and gateway images
and deploy that exact commit. Tag images by full commit SHA and deploy using
recorded registry digests, not mutable `latest` tags. Never publish or deploy
pull-request code with production credentials. Retain previous release images.

Use GitHub's scoped workflow token for GHCR pushes. Packages may remain private;
the VPS then uses an operator-provisioned read-only package credential. Do not
make packages public automatically. Record all three digests with the commit
and matching Compose configuration in a small release bundle.

Use native OpenSSH/SCP from the GitHub-hosted runner to deliver that bundle and
invoke its deployment script. Configure host, port, user, installation path,
private key, and independently verified known-hosts entry through the production
environment. Require strict host-key checking. A dedicated deployment account
needs appropriate Docker access, which is effectively privileged host access.
Application secrets remain on the VPS, not in CI archives or command output.

Serialize production jobs without cancelling an active deployment. Add a
host-side lock so manual and automated executions cannot overlap. Restrict
production credentials to main; no manual approval is required after routine
main merges, preserving the issue's automatic-deployment requirement.

## Deployment transaction and rollback

Automatic updates require an existing, healthy, recorded baseline release.
Document explicit first-install/baseline adoption rather than silently treating
missing prior state as a rollback-capable deployment. Use fixed installation
state paths, not git resets or checkout changes over operator files.

1. Validate the bundle, configuration, prior release, and available disk space;
   pull every new image before interrupting the running installation.
2. Quiesce backend and worker with their existing graceful-stop bounds. This
   single-VPS approach permits downtime; zero-downtime deployment is not promised.
3. Create a nonempty PostgreSQL custom-format snapshot in a private directory,
   with restrictive permissions. Snapshot failure prevents migration and rollout.
4. Restore that snapshot into an isolated temporary PostgreSQL instance. Run
   the candidate image's existing schema initializer against the copy. Verify
   the previous backend's readiness against the migrated copy as a smoke check.
   Preflight must not touch production schema, media, or external publishing.
5. Only after successful rehearsal, run the candidate schema initializer against
   production, using its existing advisory lock and transactional migrations.
6. Start candidate backend, worker, and gateway without rebuilding or changing
   the database image/volumes. Wait for all container health probes and verify
   public HTTPS `/ready` and `/web-health.txt`, with bounded retries/timeouts.
7. Record the new release as current only after every health check succeeds.

Any failure after quiescing restores the previous release configuration and
images and verifies their health. Preflight/snapshot failure restarts unchanged
services. Rollback failure produces a failed deployment requiring operator
intervention; it must not be reported as a successful recovery.

Do not automatically downgrade or restore the production database: doing so can
erase subsequent writes or desynchronize media. Automatic migrations must be
expand-only and compatible with the previous containers. Destructive changes
require a separately reviewed manual migration, outside routine auto-deploy.
Previous-image readiness is a smoke check, not proof of all semantic schema
compatibility. Document this limitation and the migration review requirement.

Clean only temporary preflight resources owned by this run. Never remove
production volumes. Preserve snapshots and previous bundles for operator-led
recovery; document retention and disk management, without silently pruning them.

## Verification and operator handoff

Add executable checks for orchestration ordering, missing baseline/credentials,
snapshot and preflight failure, live migration failure, failed candidate health,
successful rollback, rollback failure, and concurrency. Supplement command-level
tests with an isolated real Compose/PostgreSQL test proving snapshot restoration,
migration rehearsal, failed-health rollback, and retained database/media markers.
CI must run the deployment checks; fixtures never address the real installation.

Test contract compatibility with compatible additions and representative breaking
changes. Check CI dependency/status behavior and release-signing requirements.
Exercise the signed APK workflow with actual keys only after operator setup.

Document GHCR authentication, SSH host-key provisioning, signing-key custody,
required-check rules, baseline adoption, both proxy modes, monitoring overrides,
snapshot permissions/retention, and manual recovery. No secrets, production
hostname, keystore, or remote repository settings are assumed to exist.

Report local commands and results separately from hosted Actions, real signing,
and live HTTPS/SSH deployment evidence. Implementing workflows is not evidence
that a signed Release exists or that branch rules and production are configured.
