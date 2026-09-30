#!/usr/bin/env bash
# Task 4 verification: production Compose, Caddy gateway, web build.
# Executable assertions (not comments). Uses a synthetic env file; never
# reads ops/.env and never prints secret values. Run from the repo root:
#   bash ops/verify-prod.sh
set -euo pipefail

# Windows WSL checkout: the `docker` stub may lack Desktop integration while
# `docker.exe` works. Fall back transparently; behavior is identical.
EXE_FALLBACK=false
if ! docker info >/dev/null 2>&1 && command -v docker.exe >/dev/null 2>&1; then
  docker() { docker.exe "$@"; }
  EXE_FALLBACK=true
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

PROD=ops/docker-compose.prod.yml
DEDICATED=ops/docker-compose.dedicated.yml
EXISTING=ops/docker-compose.existing-proxy.yml
CADDYFILE=ops/gateway/Caddyfile
GATEWAY_DOCKERFILE=ops/gateway/Dockerfile

# ---- Phase A: required files exist -------------------------------------
for f in "$PROD" "$DEDICATED" "$EXISTING" "$CADDYFILE" "$GATEWAY_DOCKERFILE" ops/verify-prod.sh; do
  if [ -f "$f" ]; then pass "file exists: $f"; else fail "file missing: $f"; fi
done
if [ -x ops/verify-prod.sh ]; then pass "ops/verify-prod.sh is executable"; else fail "ops/verify-prod.sh is not executable"; fi

# ---- Phase B: Caddyfile static routing assertions -----------------------
if [ -f "$CADDYFILE" ]; then
  grep -q "reverse_proxy backend:8000" "$CADDYFILE" \
    && pass "Caddyfile proxies to backend:8000" \
    || fail "Caddyfile missing 'reverse_proxy backend:8000'"
  grep -q "/api/\*" "$CADDYFILE" \
    && pass "Caddyfile matches /api/*" \
    || fail "Caddyfile missing /api/* matcher"
  grep -q "/pub/\*" "$CADDYFILE" \
    && pass "Caddyfile matches signed-artifact /pub/*" \
    || fail "Caddyfile missing /pub/* matcher"
  grep -q "try_files {path} /index.html" "$CADDYFILE" \
    && pass "Caddyfile has SPA fallback" \
    || fail "Caddyfile missing SPA fallback 'try_files {path} /index.html'"
  if grep -Eq '^[[:space:]]*(rewrite|uri[[:space:]]+replace)' "$CADDYFILE"; then
    fail "Caddyfile must not rewrite proxied paths"
  else
    pass "Caddyfile performs no path rewrite"
  fi
  if grep -q "media" "$CADDYFILE"; then
    fail "Caddyfile must not reference the media volume"
  else
    pass "Caddyfile mounts no media volume"
  fi
  grep -q "web-health.txt" "$CADDYFILE" \
    && pass "Caddyfile serves the built web-health asset" \
    || fail "Caddyfile missing the web-health asset route"
  grep -q "127.0.0.1:8081" "$CADDYFILE" \
    && pass "Caddyfile has a loopback-only probe listener" \
    || fail "Caddyfile missing the loopback probe listener"
  # Access logs are JSON, and they lose the two request parts that carry
  # secrets outright rather than masking a list of known parameter names.
  grep -q "wrap json" "$CADDYFILE" \
    && pass "Caddyfile emits JSON access logs" \
    || fail "Caddyfile access logs are not JSON"
  grep -q "request>uri delete" "$CADDYFILE" \
    && pass "Caddyfile drops the full request URI from access logs" \
    || fail "Caddyfile does not drop the request URI from access logs"
  grep -q "request>headers delete" "$CADDYFILE" \
    && pass "Caddyfile drops request headers from access logs" \
    || fail "Caddyfile does not drop request headers from access logs"
  if grep -qE '^[[:space:]]*query[[:space:]]' "$CADDYFILE"; then
    fail "Caddyfile must not rely on masking individual query parameters"
  else
    pass "Caddyfile does not mask individual query parameters"
  fi
fi

# ---- Phase C: synthetic env + both modes render --------------------------
# Synthetic env lives inside the repo so a Windows docker.exe fallback can
# read it (foreign /tmp paths are invisible to it). Removed on exit.
SYNTH_ENV="$ROOT/.verify-prod-synth.env"
ENV_ARG="$SYNTH_ENV"
if [ "$EXE_FALLBACK" = true ]; then ENV_ARG="$(wslpath -w "$SYNTH_ENV")"; fi
PROJ="verifyprod$$"
cleanup() {
  docker compose -p "$PROJ" --env-file "$ENV_ARG" -f "$PROD" -f "$EXISTING" down -v >/dev/null 2>&1 || true
  rm -f "$SYNTH_ENV"
}
trap cleanup EXIT

# Synthetic placeholders only. Values are never echoed.
cat >"$SYNTH_ENV" <<'EOF'
POSTGRES_PASSWORD=verify-prod-synthetic
DOMAIN=deploy.example.test
PUBLIC_BASE_URL=https://deploy.example.test
SIGNED_URL_SECRET=verify-prod-synthetic-secret
META_APP_ID=verify
META_APP_SECRET=verify
META_TOKEN_ENCRYPTION_KEY=verify
META_REDIRECT_URI=https://deploy.example.test/api/meta/oauth/callback
META_ALLOWED_RETURN_URIS=https://deploy.example.test/callback
COOKIE_SECURE=true
GATEWAY_HTTP_PORT=9080
TRUSTED_PROXIES=private_ranges
EOF

render_ok=true
for mode in "$DEDICATED" "$EXISTING"; do
  if docker compose --env-file "$ENV_ARG" -f "$PROD" -f "$mode" config >/dev/null 2>/dev/null; then
    pass "config renders: $mode"
  else
    fail "config renders: $mode"
    render_ok=false
  fi
done

check_mode() {
  local mode="$1" label="$2"
  local json
  json="$(docker compose --env-file "$ENV_ARG" -f "$PROD" -f "$mode" config --format json 2>/dev/null)"
  # $1=json on stdin; assertions via python3 without echoing secrets.
  assert() { # $1=description, $2=python expr over cfg (truthy expected)
    if printf '%s' "$json" | python3 -c "import json,sys; cfg=json.load(sys.stdin); sys.exit(0 if ($2) else 1)"; then
      pass "[$label] $1"
    else
      fail "[$label] $1"
    fi
  }
  assert "named volumes db-data/media-data/caddy-data" \
    "'db-data' in cfg.get('volumes',{}) and 'media-data' in cfg.get('volumes',{}) and 'caddy-data' in cfg.get('volumes',{})"
  assert "no bind driver_opts on prod volumes" \
    "all('driver_opts' not in v for v in cfg.get('volumes',{}).values())"
  assert "db publishes no host ports" \
    "not cfg['services']['db'].get('ports')"
  assert "backend publishes no host ports" \
    "not cfg['services']['backend'].get('ports')"
  assert "init runs python -m dojo.schema" \
    "'dojo.schema' in ' '.join(str(x) for x in cfg['services']['init'].get('command',[]))"
  assert "init DATABASE_URL uses @db:5432" \
    "'@db:5432' in str(cfg['services']['init'].get('environment',{}))"
  assert "backend SKIP_CREATE_ALL=1" \
    "str(cfg['services']['backend'].get('environment',{}).get('SKIP_CREATE_ALL'))=='1'"
  assert "worker SKIP_CREATE_ALL=1" \
    "str(cfg['services']['worker'].get('environment',{}).get('SKIP_CREATE_ALL'))=='1'"
  assert "backend waits for init success" \
    "cfg['services']['backend'].get('depends_on',{}).get('init',{}).get('condition')=='service_completed_successfully'"
  assert "worker waits for init success" \
    "cfg['services']['worker'].get('depends_on',{}).get('condition',cfg['services']['worker'].get('depends_on',{})) and cfg['services']['worker']['depends_on'].get('init',{}).get('condition')=='service_completed_successfully'"
  assert "worker stop grace is 120s" \
    "cfg['services']['worker'].get('stop_grace_period') in ('120s','2m0s','2m')"
  # Health checks and log bounds are asserted on the RENDERED config, so a
  # value that only looks right in the YAML source (an inherited default, a
  # value only the shell environment supplies) cannot pass here.
  assert "every service bounds logs to 3x10m json-file" \
    "all(s.get('logging',{}).get('driver')=='json-file' and s['logging']['options'].get('max-size')=='10m' and s['logging']['options'].get('max-file')=='3' for s in cfg['services'].values())"
  assert "backend probes /ready, not /health" \
    "any('/ready' in str(t) for t in cfg['services']['backend']['healthcheck']['test']) and not any(\"'/health'\" in str(t) for t in cfg['services']['backend']['healthcheck']['test'])"
  assert "backend readiness HTTP call is bounded inside the probe timeout" \
    "any('timeout=' in str(t) for t in cfg['services']['backend']['healthcheck']['test'])"
  assert "worker probes the health CLI" \
    "any('worker.health' in str(t) for t in cfg['services']['worker']['healthcheck']['test'])"
  assert "gateway probes the loopback web health asset" \
    "any('8081' in str(t) and 'web-health.txt' in str(t) for t in cfg['services']['gateway']['healthcheck']['test'])"
  assert "probe cadence is 15s/5s/3/30s on backend, worker and gateway" \
    "all(cfg['services'][s]['healthcheck'].get(k)==v for s in ('backend','worker','gateway') for k,v in (('interval','15s'),('timeout','5s'),('retries',3),('start_period','30s')))"
  assert "worker health record path is container-local" \
    "str(cfg['services']['worker']['environment'].get('WORKER_HEALTH_PATH'))=='/tmp/dojo-worker-health.json'"
  assert "worker idle deadline is 120s and busy deadline 3600s" \
    "str(cfg['services']['worker']['environment'].get('WORKER_HEALTH_IDLE_SECONDS'))=='120' and str(cfg['services']['worker']['environment'].get('WORKER_HEALTH_BUSY_SECONDS'))=='3600'"
  assert "base production sends no operational alerts" \
    "str(cfg['services']['worker']['environment'].get('MONITORING_ENABLED','false')).lower()!='true'"
  assert "base production exposes no FCM credentials" \
    "'GOOGLE_APPLICATION_CREDENTIALS' not in cfg['services']['worker'].get('environment',{})"
  assert "gateway mounts no media volume" \
    "not any('media-data' in str(v) for v in cfg['services']['gateway'].get('volumes',[]))"
  if [ "$label" = "dedicated" ]; then
    assert "gateway publishes 80 and 443" \
      "'80' in [str(q.get('published', q)) if isinstance(q, dict) else str(q) for q in cfg['services']['gateway'].get('ports',[])] and '443' in [str(q.get('published', q)) if isinstance(q, dict) else str(q) for q in cfg['services']['gateway'].get('ports',[])]"
  else
    assert "gateway HTTP is loopback-bound" \
      "any('127.0.0.1' in str(p) for p in cfg['services']['gateway'].get('ports',[]))"
  fi
}

if [ "$render_ok" = true ]; then
  if command -v python3 >/dev/null 2>&1; then
    check_mode "$DEDICATED" "dedicated"
    check_mode "$EXISTING" "existing-proxy"
  else
    fail "python3 is required for config assertions"
  fi
fi

# ---- Phase D: images build -----------------------------------------------
if [ "$render_ok" = true ]; then
  if docker compose --env-file "$ENV_ARG" -f "$PROD" -f "$DEDICATED" build backend worker gateway >/dev/null 2>&1; then
    pass "images build: backend worker gateway"
  else
    fail "images build: backend worker gateway"
  fi
  GATEWAY_IMAGE="$(docker compose --env-file "$ENV_ARG" -f "$PROD" -f "$DEDICATED" config --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["gateway"]["image"])')"
  if docker run --rm -e SITE_ADDRESS=deploy.example.test -e TRUSTED_PROXIES=private_ranges --entrypoint caddy "$GATEWAY_IMAGE" validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    pass "Caddyfile validates inside gateway image"
  else
    fail "Caddyfile validates inside gateway image"
  fi
fi

# ---- Phase E: recreation keeps persisted data -----------------------------
if [ "$render_ok" = true ]; then
  docker compose -p "$PROJ" --env-file "$ENV_ARG" -f "$PROD" -f "$EXISTING" up -d db >/dev/null 2>&1 \
    && pass "verify stack db starts" \
    || fail "verify stack db starts"
  DB_ID="$(docker compose -p "$PROJ" ps -q db 2>/dev/null)"
  healthy=false
  for _ in $(seq 1 24); do
    if docker exec "$DB_ID" pg_isready -U dojo -d dojo >/dev/null 2>&1; then healthy=true; break; fi
    sleep 5
  done
  if [ "$healthy" = true ]; then pass "verify db becomes healthy"; else fail "verify db becomes healthy"; fi
  if docker exec "$DB_ID" psql -U dojo -d dojo -v ON_ERROR_STOP=1 -c "CREATE TABLE verify_sentinel(v text);" -c "INSERT INTO verify_sentinel VALUES ('keep-me');" >/dev/null 2>&1; then
    pass "sentinel row written"
  else
    fail "sentinel row written"
  fi
  docker compose -p "$PROJ" --env-file "$ENV_ARG" -f "$PROD" -f "$EXISTING" up -d --force-recreate db >/dev/null 2>&1
  DB_ID="$(docker compose -p "$PROJ" ps -q db 2>/dev/null)"
  for _ in $(seq 1 24); do
    if docker exec "$DB_ID" pg_isready -U dojo -d dojo >/dev/null 2>&1; then break; fi
    sleep 5
  done
  if [ "$(docker exec "$DB_ID" psql -U dojo -d dojo -tAc "SELECT count(*) FROM verify_sentinel;" 2>/dev/null | tr -d '[:space:]')" = "1" ]; then
    pass "recreation keeps sentinel row"
  else
    fail "recreation keeps sentinel row"
  fi
  docker compose -p "$PROJ" --env-file "$ENV_ARG" -f "$PROD" -f "$EXISTING" down -v >/dev/null 2>&1 \
    && pass "verify stack cleaned up" \
    || fail "verify stack cleaned up"
fi

echo "verify-prod: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
