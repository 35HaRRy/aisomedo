# Production deployment

Single-VPS deployment: PostgreSQL, FastAPI backend, Python worker, Caddy
gateway serving the built React frontend with SPA fallback and verbatim
`/api/*`, `/pub/*`, `/health` proxying to the backend. Each installation
lives at its domain root.

## Prerequisites (VPS, DNS, ports)

- One Linux host with Docker + Compose plugin, ports 80/443 reachable.
- **Dedicated-domain mode:** `DOMAIN` (e.g. `dojo.example.com`) with an A/AAAA
  record pointing at the VPS. Caddy obtains and renews public TLS automatically
  (state persists in the `caddy-data` volume).
- **Existing-proxy mode:** the upstream reverse proxy owns TLS and forwards
  plain HTTP to the gateway on loopback
  `127.0.0.1:${GATEWAY_HTTP_PORT:-9080}` (host-based), or to
  `http://gateway:80` over an external Docker network (container-based —
  uncomment the `proxy-upstream` block in
  `ops/docker-compose.existing-proxy.yml` and set `EXTERNAL_NETWORK_NAME`).
- No host ports are published for `db` or `backend` in either mode.

## Environment

Copy `ops/.env.example` to `ops/.env` and fill every value (placeholders only
in the example — never real credentials). **Always pass
`--env-file ops/.env`**: prod services deliberately declare no `env_file`,
so a missing flag fails fast instead of booting with empty defaults.

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | yes | Database password (also `POSTGRES_DB/USER`, defaults `dojo`) |
| `DOMAIN` | dedicated | Public domain; Caddy `SITE_ADDRESS`, auto TLS |
| `PUBLIC_BASE_URL` | yes | Public origin fallback for signed URLs/OAuth |
| `PUBLIC_HTTPS_ORIGIN` | prod | Canonical public origin (must be `https` in prod); wins over `PUBLIC_BASE_URL` when set; wired into backend AND worker signed-URL/OAuth builders |
| `SIGNED_URL_SECRET` | yes | HMAC secret for signed artifact URLs |
| `COOKIE_SECURE` | no (`true`) | `Secure` session cookies; keep `true` in prod |
| `TRUSTED_PROXIES` | no (`private_ranges`) | Trust set for forwarded headers, both layers: Caddy `trusted_proxies` (upstream→gateway) and backend middleware (gateway→backend) |
| `GATEWAY_HTTP_PORT` | existing-proxy | Loopback HTTP port, default `9080` |
| `EXTERNAL_NETWORK_NAME` | container upstream | External Docker network of a container-based proxy (empty otherwise) |
| `META_*` | OAuth | `META_APP_ID/SECRET`, `META_REDIRECT_URI` (public `https://…/api/meta/oauth/callback`), `META_ALLOWED_RETURN_URIS` (public origins), `META_TOKEN_ENCRYPTION_KEY`, `META_OAUTH_SCOPE`, `META_GRAPH_VERSION` |
| `WORKER_INTERVAL_SECONDS` | no (`10`) | Scheduler tick interval |
| `FCM_CREDENTIALS_FILE` | monitoring only | Host path to the Firebase service-account JSON; mounted read-only as a Compose secret. **Required** (Compose fails the render) when `ops/docker-compose.monitoring.yml` is used, and read by no other file |
| `FCM_PROJECT_ID` | monitoring only | Firebase project (`GOOGLE_CLOUD_PROJECT` is also read). **Required** when `ops/docker-compose.monitoring.yml` is used: FCM addresses by project, and the worker refuses to start without one |
| `MONITORING_*` | no | Disk sampling interval, thresholds and targets; see the monitoring runbook |

`ops/docker-compose.monitoring.yml` is an optional third `-f` that adds disk
monitoring and FCM alerts. It is not part of the base contract below, and CI
renders the base files without it.

Trust is configured in two separate places on purpose: upstream-proxy→gateway
in `ops/gateway/Caddyfile` (`trusted_proxies`), gateway→backend in
`backend/src/backend/proxy.py` (`TRUSTED_PROXIES`). Uvicorn `--proxy-headers`
stays disabled (`backend/Dockerfile`) so the ASGI middleware is the single
backend normalization layer. Forwarded `X-Forwarded-For/Proto` from any peer
outside `TRUSTED_PROXIES` is ignored — pairing-throttle identity and scheme
detection fall back to the direct peer. Frontend API calls are same-origin in
both environments; no frontend origin setting exists.

## Fresh install

```bash
cp ops/.env.example ops/.env   # then fill secrets + DOMAIN + public origins
# Dedicated domain (Caddy owns :80/:443, auto TLS):
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.dedicated.yml up -d --build
# Existing proxy (upstream owns TLS, gateway on loopback HTTP):
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.existing-proxy.yml up -d --build
```

Startup order is serialized: `db` (healthy) → `init` (runs
`python -m dojo.schema` once to completion; backend/worker set
`SKIP_CREATE_ALL=1` so the initializer owns the schema) → `backend`+`worker`.
`gateway` waits for `backend` healthy.

Existing databases upgrade automatically on `init`: fresh DBs migrate to head;
versioned DBs upgrade; unversioned `create_all` DBs are structurally validated
before stamping (unsupported schemas are rejected, never stamped — see
task-3 report). Emission-dedup preflight (`0014`) reports conflicting row IDs
and aborts before any mutation rather than deleting history. `init` uses
`restart: "no"`: if it exits non-zero, inspect `docker logs dojo-prod-init-1`
and fix the reported conflict before restarting.

## Health verification

```bash
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml ps
curl -s https://<DOMAIN>/ready             # {"status":"ok"} via gateway
curl -s https://<DOMAIN>/web-health.txt    # built web asset, independent of the API
curl -s https://<DOMAIN>/api/packages/active -o /dev/null -w '%{http_code}\n'  # 401 = routed, not SPA
```

`GET /` and deep links (e.g. `/some/deep/link`) return the SPA `index.html`;
`/api/*`, `/pub/*`, `/health`, `/ready` never fall through to it. Backend/database ports
are unreachable from the host by design.

Container health (`ps` column `STATUS`) reflects three probes: backend `/ready`,
the worker health CLI, and the gateway's loopback web-health asset. All run on
a 15s interval, 5s timeout, 3 retries, 30s start period. Docker's `unhealthy`
is diagnostic only — `restart: unless-stopped` does not restart an unhealthy
container that is still running, so recovery is an operator action. Diagnosis
and recovery steps are in
[`docs/rehberler/production-monitoring.md`](../rehberler/production-monitoring.md)
§3.

## Worker scaling

Multiple workers are safe: scheduler emission is leadership-gated
(one elected scheduler per turn via a transaction-scoped advisory lock;
followers skip) with database-backed idempotency underneath, and job execution
uses atomic `SELECT … FOR UPDATE SKIP LOCKED` claims. Scale with
`docker compose … up -d --scale worker=N` (N≥1); in-flight renders run at most
until the 120 s `stop_grace_period` on SIGTERM.

## Restart

```bash
docker compose --env-file ops/.env -p dojo-prod \
  -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml restart
```

`restart: unless-stopped` on all long-lived services; `init` stays `no`.

## Recorded releases and safe updates (#39)

`ops/deploy.py` is a Linux, Python 3.12+ CLI using Docker Compose's `--wait`
support, not a new daemon. Production project identity stays `dojo-prod`.
Its `bundle`/`validate` commands also work outside Linux. Use a private
installation root (example `/srv/aisomedo`, mode 0700) containing:

- `config/production.env`: the operator-owned production settings (mode 0600).
- `releases/<full-commit-sha>/`: immutable digest-pinned bundle and matching Compose files.
- `current.json`: last verified successful release; updated atomically only after health checks.
- `snapshots/`: private pre-deployment PostgreSQL dumps, never uploaded to Actions.
- `deploy.lock`: host lock shared by manual and automated deployments.

Generate a bundle from the checked checkout, substituting real immutable image
digests (lowercase 64 hex characters), not tags:

```bash
python3 ops/deploy.py bundle --sha "$COMMIT_SHA" \
  --backend "ghcr.io/OWNER/aisomedo-backend@sha256:$BACKEND_DIGEST" \
  --worker "ghcr.io/OWNER/aisomedo-worker@sha256:$WORKER_DIGEST" \
  --gateway "ghcr.io/OWNER/aisomedo-gateway@sha256:$GATEWAY_DIGEST" \
  --output release-bundle
python3 ops/deploy.py validate --release release-bundle
```

Registry paths must be lowercase. Before adopting an existing installation,
explicitly pull/start a known baseline with its bundled files and `images.json`
override, using `--env-file /srv/aisomedo/config/production.env -p dojo-prod`.
Perform the volume-adoption procedure below if this is not already the same
production project. Check the running database and all three application health
checks, then record the baseline:

```bash
python3 release-bundle/deploy.py adopt --release release-bundle \
  --root /srv/aisomedo --mode dedicated --origin https://dojo.example.com
```

`adopt` verifies running image IDs against every recorded digest and refuses an
already recorded baseline. A normal deploy refuses missing or unhealthy baseline
state. This deliberately prevents silently claiming rollback capability on a
first install. For existing proxies use `--mode existing-proxy`; add `--monitoring`
when the existing installation has its FCM configuration. Keep any custom external
network override in the checked Compose configuration so releases preserve it.

Update manually with the same CLI that SSH automation invokes:

```bash
python3 candidate-bundle/deploy.py deploy --release candidate-bundle \
  --root /srv/aisomedo --mode dedicated --origin https://dojo.example.com
```

The CLI locks the installation, validates/pulls images, checks space (twice live
database size plus 1 GiB for the dump area), gracefully stops backend/worker,
and takes a custom-format `pg_dump`. Expect API downtime during this operation.
It restores the dump in an isolated internal PostgreSQL network, runs candidate
migrations there, and checks the previous backend against the migrated copy.
The rehearsal receives no production media or external-service credentials.
Only then does it run the live schema initializer and replace backend/worker/
gateway containers. Database and durable volumes are never recreated.

Rollout health must pass container probes and public HTTPS `/ready` and
`/web-health.txt`. Snapshot, preflight, migration, or health failure restores
previous images/configuration and verifies recovery; failed rollback remains a
failed deployment requiring operator intervention. **No automatic DB restore or
schema downgrade occurs.** Automatic migrations must be expand-only and work with
previous containers. Previous-image readiness is only a smoke test, not proof of
all query/publication semantics; review migration compatibility before merge.

Snapshots are mode 0600 under a mode 0700 directory; they contain sensitive
installation state. Keep at least the last successful baseline, its image
digests, and the corresponding snapshot. Set an operator-owned retention policy
and monitor both the installation filesystem and Docker's data root: rehearsal
also needs database-sized space in Docker storage. The CLI never silently prunes
snapshots, releases, or images. This safety snapshot is not a substitute for the
encrypted off-host backup/restore procedure.

Catchable INT/TERM/HUP triggers bounded recovery. SIGKILL, power loss, or host
failure cannot run recovery: inspect `current.json`, containers, snapshots, and
the retained failed bundle. Start only the last recorded application services
with their previous bundle and `up --no-build --pull never --no-deps --wait`;
do not blindly rerun previous migrations or restore a dump over live data.
If a DB restore is necessary, keep applications stopped, take another forensic
snapshot, and use the reviewed manual backup/restore procedure.

Live schema initialization uses a unique invocation-owned container name and
PostgreSQL application name. On interruption/timeout, recovery removes that
initializer and terminates/verifies only its tagged DB sessions before restarting
previous applications. If termination cannot be verified, rollback fails closed
with applications still stopped for operator intervention. Automatic releases
also reject changes to persistent-volume definitions and service volume mounts
before quiescing; storage relocation belongs in a separate reviewed procedure.

### GitHub Actions / SSH operator setup

Local workflow tests do not configure GitHub rules or the VPS. Before enabling
automatic updates, complete these operator-owned steps:

1. On the VPS, provision Python 3.12+, Docker/Compose with `up --wait`, and a
   dedicated SSH deployment account. Docker socket/group access is effectively
   root access: protect this account and its key accordingly. Own the private
   installation directory and `config/production.env` with this account.
2. Authenticate the account to GHCR using a read-only `read:packages` credential
   with access to all three packages. Use `docker login ghcr.io --password-stdin`
   from a trusted session; do not put this token in Actions or release bundles.
   Retain previous digests in GHCR and locally; an expired credential must fail
   image pulling before applications stop.
3. Explicitly install/adopt a healthy baseline as above. Verify its bundle files
   and running image IDs, public HTTPS, existing persistent volumes, monitoring
   settings, and available snapshot/Docker storage. Put no live config in Git.
4. Create GitHub environment `production`, restricted to main. Routine main
   deployment has no approval gate, as required by #39. Configure variables
   `DEPLOY_HOST` (DNS name or IPv4), `DEPLOY_PORT` (1–65535), `DEPLOY_USER`,
   `DEPLOY_ROOT` (absolute path with alphanumeric/underscore/hyphen components),
   `DEPLOY_MODE` (`dedicated` or `existing-proxy`), `DEPLOY_ORIGIN` (public HTTPS
   origin), and `DEPLOY_MONITORING` (`true` or `false`). These restricted inputs
   prevent shell interpolation; paths with spaces or dots are not supported.
5. Set secrets `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS` in that environment.
   Verify the VPS host key fingerprint through an independent trusted channel
   (provider console/operator), then store the corresponding known_hosts line.
   For a non-default port use `[host]:port`. Do not obtain trust automatically
   through unattended `ssh-keyscan`; host-key mismatch must fail closed.
6. Configure main branch rules to require the aggregate `required` check from
   workflow `ci` (often displayed as `ci / required`; confirm exact context after
   the first hosted run). Require checks before merge and cover merge queues.
   Restrict bypass permissions. Workflow YAML alone does not prevent merges.

Every main push that passes all required suites publishes full-SHA-tagged GHCR
images and a digest-pinned release artifact. Production deployment jobs serialize
without cancelling an active rollout. Jobs skip superseded commits if main has
advanced before the serialized job starts. SSH/SCP use strict known-host checks
and private temporary key files. Bundles stage under `incoming-<run>-<attempt>` and
remain available for diagnosis; CLI records verified releases separately. Remove
old staging directories manually only after confirming they are not active and
their release/snapshot is retained. No SSH or package credentials exist in PR jobs.

Contract checks compare PR/merge-queue bases and the preceding push revision.
A newly created branch compares its parent; only the genuine initial repository
commit can bootstrap without a prior contract. Missing older contracts fail
instead of silently skipping compatibility checks.

Before treating #39 as operationally complete, capture a hosted passing required
check and blocked failed-check merge, a real signed Android Release, and a real
SSH deployment plus controlled failed-health recovery. This implementation does
not itself prove any of those operator-dependent acceptance criteria.

## Volume lifecycle (never silently start empty)

Project/volume naming is frozen by `name: dojo-prod`: volumes are
`dojo-prod_db-data`, `dojo-prod_media-data`, `dojo-prod_caddy-data`. Always
pass `-p dojo-prod` — a different prefix creates EMPTY volumes next to a live
installation. `docker compose up --force-recreate` keeps all data (volumes are
not recreated); `down` without `-v` preserves them too. Before a first prod
`up` against a host that may hold data under another prefix:

```bash
docker volume ls | grep -E 'db-data|media-data|caddy-data'
docker volume inspect <existing-volume>   # confirm Mountpoint has real data
docker volume create dojo-prod_db-data
docker run --rm -v <old-volume>:/from -v dojo-prod_db-data:/to alpine cp -a /from/. /to/
```

Verify row/file counts before starting prod (same pattern for `media-data`).

## Smoke checklist

- [ ] Both mode configs render:
  `docker compose --env-file ops/.env -f ops/docker-compose.prod.yml -f ops/docker-compose.<mode>.yml config`
- [ ] `bash ops/verify-prod.sh` green (local/VPS runbook; not in CI)
- [ ] `bash ops/verify-monitoring.sh` green (monitoring contract; not in CI)
- [ ] `GET /` → 200 SPA HTML; deep link → 200 same `index.html`
- [ ] `GET /ready` → `{"status":"ok"}` (backend, not SPA)
- [ ] `GET /web-health.txt` → 200; then `stop backend` → `/ready` fails while
      `/web-health.txt` still returns 200 (readiness and web health are independent).
      Covered for the backend itself by `verify-prod.sh` Phase F and for the
      gateway by `verify-monitoring.sh` Phase H; re-run the manual form here on
      the deployed stack, since the hosted monitor depends on it.
- [ ] `GET /api/packages/active` → 401; `GET /pub/badtoken` → 404 (proxied)
- [ ] Browser pairing sets `Secure`, `HttpOnly`, `SameSite=Lax` cookie; renewal on auth re-issues it
- [ ] Pairing throttle keys on the real client IP through the proxy chain
- [ ] `docker compose … up --force-recreate` keeps db/media content
- [ ] VPS-gated (real public HTTPS + cert issuance on a configured domain):
      not exercised locally — record DNS, `curl -v https://<DOMAIN>/health`
      (issuer, expiry), and Caddy `caddy-data` persistence in the completion
      report, kept distinct from local proxy-test evidence above.
