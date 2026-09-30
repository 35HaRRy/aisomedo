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

# The Caddyfile deletes the request uri and headers from the access log, but
# NOT the response headers, so whether a session cookie stays out of the log
# depends on Caddy's own credential-header redaction. A floating tag lets that
# default move between builds; Phase I of verify-monitoring.sh asserts the
# redaction, and it can only mean something against a known version.
if grep -Eq '^FROM caddy:[0-9]+\.[0-9]+\.[0-9]+-alpine$' "$GATEWAY_DOCKERFILE"; then
  pass "gateway image pins an exact Caddy version"
else
  fail "gateway image pins an exact Caddy version"
fi

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
  rm -f "$SYNTH_ENV" "$ROOT/.verify-prod-health.env"
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

# The three worker-health settings are documented as .env settings, so the
# deployment must interpolate them. The assertions above only prove the
# DEFAULTS render; without a non-default render, a hardcoded literal in the
# compose file would pass them and silently ignore an operator's tuning.
check_health_passthrough() {
  local json
  json="$(docker compose --env-file "$HEALTH_ENV_ARG" -f "$PROD" -f "$EXISTING" \
    config --format json 2>/dev/null)" || { fail "health-override config renders"; return 0; }
  local ok
  if printf '%s' "$json" | python3 -c "
import json, sys
env = json.load(sys.stdin)['services']['worker']['environment']
sys.exit(0 if (
    str(env.get('WORKER_HEALTH_PATH')) == '/tmp/verify-worker-health.json'
    and str(env.get('WORKER_HEALTH_IDLE_SECONDS')) == '180'
    and str(env.get('WORKER_HEALTH_BUSY_SECONDS')) == '1800'
) else 1)
"; then
    pass "worker health path and both deadlines pass through from .env"
  else
    fail "worker health path and both deadlines pass through from .env"
  fi
  # And the probe must still find the record at the tuned path: the healthcheck
  # runs the CLI with no argument, so a path only the worker reads is a contract
  # the deployment cannot satisfy.
  if printf '%s' "$json" | python3 -c "
import json, sys
cfg = json.load(sys.stdin)
tests = cfg['services']['worker']['healthcheck']['test']
env = cfg['services']['worker']['environment']
sys.exit(0 if 'WORKER_HEALTH_PATH' not in ' '.join(str(t) for t in tests) else 1)
"; then
    pass "worker health probe takes no path argument (it resolves the env one)"
  else
    fail "worker health probe takes no path argument (it resolves the env one)"
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

# ---- Phase C2: the documented health settings really are settings ----------
HEALTH_ENV="$ROOT/.verify-prod-health.env"
HEALTH_ENV_ARG="$HEALTH_ENV"
if [ "$EXE_FALLBACK" = true ]; then HEALTH_ENV_ARG="$(wslpath -w "$HEALTH_ENV")"; fi
{
  cat "$SYNTH_ENV"
  # Deliberately different from every default, so a value that is read must
  # differ from one that is hardcoded.
  cat <<'EOF'
WORKER_HEALTH_PATH=/tmp/verify-worker-health.json
WORKER_HEALTH_IDLE_SECONDS=180
WORKER_HEALTH_BUSY_SECONDS=1800
EOF
} >"$HEALTH_ENV"
if [ "$render_ok" = true ]; then
  if command -v python3 >/dev/null 2>&1; then
    check_health_passthrough
  else
    fail "python3 is required for config assertions"
  fi
fi
rm -f "$HEALTH_ENV"

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

# ---- Phase F: real backend readiness fails and recovers --------------------
# Phase E only proves volume persistence, so the real backend's readiness
# contract was unverified by any script. This starts the actual backend against
# the actual database and takes the database away and back, which is the
# failure the review focus names. The gateway is not involved: this is the
# backend's own bounded DB check, which Task 6's production probe depends on.
if [ "$render_ok" = true ]; then
  stack() { docker compose -p "$PROJ" --env-file "$ENV_ARG" -f "$PROD" -f "$EXISTING" "$@"; }
  # Built here, not assumed: a stale dojo-backend:latest from an earlier run
  # would pass or fail on code that is not the code under test. IMAGE_TAG is
  # already this run's suffix, so the tag cannot collide with anything else.
  if docker compose --env-file "$ENV_ARG" -f "$PROD" -f "$EXISTING" build backend >/dev/null 2>&1; then
    pass "verify stack backend image builds"
  else
    fail "verify stack backend image builds"
  fi
  # $1=container id -> "ok" when /ready answers 200, "503" when the backend
  # itself reports unavailable, and "down" when the request cannot be made at
  # all. The three are different facts and only the middle one is a readiness
  # failure: a dead process also stops answering, and would otherwise satisfy
  # "fails while the database is down" for the wrong reason.
  ready_state() {
    docker exec "$1" .venv/bin/python -c \
      "import urllib.error, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4)
except urllib.error.HTTPError as exc:
    print(exc.code)
except Exception:
    print('down')
else:
    print('ok')" 2>/dev/null || echo "down"
  }
  backend_running() { # $1=container id
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
  }
  wait_ready() { # $1=container id, $2=expected state, $3=attempts
    local i
    for i in $(seq 1 "$3"); do
      if [ "$(ready_state "$1")" = "$2" ]; then return 0; fi
      sleep 2
    done
    return 1
  }
  stack up -d backend >/dev/null 2>&1 \
    && pass "verify stack backend starts" \
    || fail "verify stack backend starts"
  # `|| true` mirrors Phase E: an empty id must be a recorded failure below,
  # not a `set -e` abort that skips every later assertion.
  BACKEND_ID="$(stack ps -q backend 2>/dev/null || true)"
  if [ -z "$BACKEND_ID" ]; then
    fail "verify stack backend has a container id"
    stack down -v >/dev/null 2>&1 || true
  else
    pass "verify stack backend has a container id"
    if wait_ready "$BACKEND_ID" ok 45; then
      pass "real backend /ready is healthy against a live database"
    else
      fail "real backend /ready is healthy against a live database"
    fi
    # Take the database away, not the backend: the API stays up and must report
    # itself unavailable, rather than stop answering for the wrong reason.
    stack stop db >/dev/null 2>&1 || true
    if backend_running "$BACKEND_ID" && wait_ready "$BACKEND_ID" 503 15; then
      pass "real backend /ready reports 503 while the database is down"
    else
      fail "real backend /ready reports 503 while the database is down"
    fi
    stack up -d db >/dev/null 2>&1 || true
    if wait_ready "$BACKEND_ID" ok 45; then
      pass "real backend /ready recovers when the database returns"
    else
      fail "real backend /ready recovers when the database returns"
    fi
    stack down -v >/dev/null 2>&1 || true
  fi
fi

echo "verify-prod: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
