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
curl -s https://<DOMAIN>/health            # {"status":"ok"} via gateway
curl -s https://<DOMAIN>/api/packages/active -o /dev/null -w '%{http_code}\n'  # 401 = routed, not SPA
```

`GET /` and deep links (e.g. `/some/deep/link`) return the SPA `index.html`;
`/api/*`, `/pub/*`, `/health` never fall through to it. Backend/database ports
are unreachable from the host by design.

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
- [ ] `GET /` → 200 SPA HTML; deep link → 200 same `index.html`
- [ ] `GET /health` → `{"status":"ok"}` (backend, not SPA)
- [ ] `GET /api/packages/active` → 401; `GET /pub/badtoken` → 404 (proxied)
- [ ] Browser pairing sets `Secure`, `HttpOnly`, `SameSite=Lax` cookie; renewal on auth re-issues it
- [ ] Pairing throttle keys on the real client IP through the proxy chain
- [ ] `docker compose … up --force-recreate` keeps db/media content
- [ ] VPS-gated (real public HTTPS + cert issuance on a configured domain):
      not exercised locally — record DNS, `curl -v https://<DOMAIN>/health`
      (issuer, expiry), and Caddy `caddy-data` persistence in the completion
      report, kept distinct from local proxy-test evidence above.
