#!/usr/bin/env bash
# Task 6 runtime verification: production monitoring deployment contract.
#
# Executable assertions (not comments). Everything it builds, starts, mounts
# and removes is named after this process, so it can never touch a real
# installation, real credentials or another project. It never reads ops/.env
# and never prints a secret value.
#
# Run from the repo root:
#   bash ops/verify-monitoring.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Docker may be a native Linux binary, a Windows CLI reached from a POSIX
# shell, or absent from a WSL distro whose Docker Desktop integration is off.
# Only the last case needs a wrapper. A Windows CLI does not understand POSIX
# paths at all, so every path handed to it is translated here rather than left
# to the shell's own argument conversion, which rewrites container-internal
# paths in the same pass and never applies to a path written INTO a file (the
# synthetic env, the compose secret path).
EXE_FALLBACK=false
if ! command -v docker >/dev/null 2>&1; then
  if command -v docker.exe >/dev/null 2>&1; then
    docker() { docker.exe "$@"; }
    EXE_FALLBACK=true
  else
    echo "verify-monitoring: docker is not available on this host" >&2
    exit 1
  fi
fi
if [ "$EXE_FALLBACK" = true ]; then
  hostpath() { wslpath -w "$1"; }
elif command -v cygpath >/dev/null 2>&1; then
  hostpath() { cygpath -w "$1"; }
else
  hostpath() { printf '%s' "$1"; }
fi

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

PROD=ops/docker-compose.prod.yml
DEDICATED=ops/docker-compose.dedicated.yml
EXISTING=ops/docker-compose.existing-proxy.yml
MONITORING=ops/docker-compose.monitoring.yml
CADDYFILE=ops/gateway/Caddyfile
# Absolute: a Windows CLI rejects a relative bind-mount source, and every path
# that reaches it goes through hostpath, which cannot resolve a bare filename.
CADDYFILE_ABS="$ROOT/ops/gateway/Caddyfile"

# ---- disposable identity ---------------------------------------------------
# One process, one suffix. Nothing below addresses a container, image, network
# or project that does not carry it, so cleanup can only ever remove this run's
# own objects.
SUFFIX="$$"
PROJ="verifymon${SUFFIX}"
GW_IMAGE="dojo-verify-gateway:${SUFFIX}"
WORKER_IMAGE="dojo-verify-worker:${SUFFIX}"
NET="verifymon-net-${SUFFIX}"
GW_DEDICATED="verifymon-gw-dedicated-${SUFFIX}"
GW_EXISTING="verifymon-gw-existing-${SUFFIX}"
BACKEND="verifymon-backend-${SUFFIX}"
RUNDIR="$ROOT/.verify-monitoring-${SUFFIX}"
SYNTH_ENV="$RUNDIR/synth.env"
DUMMY_SECRET="$RUNDIR/fcm-dummy.json"
BAD_SECRET="$RUNDIR/fcm-invalid.json"
STUB="$RUNDIR/backend-stub.py"
DEDICATED_CADDYFILE="$RUNDIR/dedicated.Caddyfile"
LOGFILE="$RUNDIR/gateway.log"
SEND_LOG="$RUNDIR/send.log"
PROJECT_LOG="$RUNDIR/project.log"
CHECK="$RUNDIR/check.py"

ENV_ARG="$(hostpath "$SYNTH_ENV")"

cleanup() {
  docker rm -f "$GW_DEDICATED" "$GW_EXISTING" "$BACKEND" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  if [ -f "$SYNTH_ENV" ]; then
    docker compose -p "$PROJ" --env-file "$ENV_ARG" \
      -f "$(hostpath "$PROD")" -f "$(hostpath "$EXISTING")" \
      -f "$(hostpath "$MONITORING")" down -v --remove-orphans \
      >/dev/null 2>&1 || true
  fi
  docker rmi -f "$GW_IMAGE" "$WORKER_IMAGE" "dojo-worker:${SUFFIX}" >/dev/null 2>&1 || true
  rm -rf "$RUNDIR"
}
trap cleanup EXIT

# ---- Phase A: required files and tooling ----------------------------------
for f in "$MONITORING" ops/verify-monitoring.sh; do
  if [ -f "$f" ]; then pass "file exists: $f"; else fail "file missing: $f"; fi
done
if [ -x ops/verify-monitoring.sh ]; then
  pass "ops/verify-monitoring.sh is executable"
else
  fail "ops/verify-monitoring.sh is not executable"
fi
if [ ! -f "$MONITORING" ]; then
  echo "verify-monitoring: $PASS passed, $FAIL failed (no monitoring override to verify)"
  [ "$FAIL" -eq 0 ]
  exit $?
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "verify-monitoring: python3 is required for config assertions" >&2
  exit 1
fi
mkdir -p "$RUNDIR"

# ---- Phase B: synthetic fixtures -----------------------------------------
# Placeholder values only. The dummy credential is not a service account: it
# carries no project, no key and no token, so nothing can be sent even if a
# process were to read it.
cat >"$DUMMY_SECRET" <<'EOF'
{
  "type": "service_account",
  "project_id": "dojo-verify-not-a-project",
  "private_key_id": "verify-monitoring-synthetic",
  "client_email": "verify-monitoring@example.invalid"
}
EOF
printf 'this is not a service account\n' >"$BAD_SECRET"

# Disposable API stand-in. Task 6 verifies that the GATEWAY routes readiness
# and the web health asset independently of each other; the readiness contract
# itself (503 on an unavailable database) is Task 1's unit-tested behavior. The
# container answers on the network alias `backend:8000`, so the unmodified
# production Caddyfile resolves it exactly as it resolves the real service.
cat >"$STUB" <<'EOF'
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Byte-identical to the backend's JSONResponse for {"status": "ok"}, so an
# assertion on the /ready body here means what it means in production.
BODY = b'{"status":"ok"}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - stdlib naming
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        # A response-side credential. The gateway deletes request headers from
        # its access log but Caddy itself emits resp_headers on every record,
        # so the session cookie is only kept out of the log by Caddy redacting
        # credential headers. Phase I asserts that it does.
        self.send_header("Set-Cookie", "session=VERIFYMONSESSION; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *_args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
EOF

cat >"$SYNTH_ENV" <<EOF
# The production files name their images dojo-<service>:${IMAGE_TAG:-latest}.
# Pinning the tag to this run's suffix is what keeps `compose run` in Phase F
# on the disposable image instead of whatever dojo-worker:latest happens to be
# on the host.
IMAGE_TAG=$SUFFIX
POSTGRES_PASSWORD=verify-monitoring-synthetic
DOMAIN=deploy.example.test
PUBLIC_BASE_URL=https://deploy.example.test
SIGNED_URL_SECRET=verify-monitoring-synthetic-secret
META_APP_ID=verify
META_APP_SECRET=verify
META_TOKEN_ENCRYPTION_KEY=verify
META_REDIRECT_URI=https://deploy.example.test/api/meta/oauth/callback
META_ALLOWED_RETURN_URIS=https://deploy.example.test/callback
COOKIE_SECURE=true
GATEWAY_HTTP_PORT=9080
TRUSTED_PROXIES=private_ranges
FCM_CREDENTIALS_FILE=$(hostpath "$DUMMY_SECRET")
FCM_PROJECT_ID=dojo-verify-not-a-project
EOF

# ---- Phase C: disposable images -------------------------------------------
if docker build -f "$(hostpath ops/gateway/Dockerfile)" -t "$GW_IMAGE" \
  "$(hostpath "$ROOT")" >/dev/null 2>&1; then
  pass "disposable gateway image builds"
else
  fail "disposable gateway image builds"
fi
# Tagged twice: once under the disposable name this script owns, and once under
# the name the production file asks for, so `compose run` in Phase F starts the
# image this run just built rather than a pre-existing dojo-worker:latest.
if docker build -f "$(hostpath worker/Dockerfile)" -t "$WORKER_IMAGE" \
  -t "dojo-worker:${SUFFIX}" "$(hostpath "$ROOT")" >/dev/null 2>&1; then
  pass "disposable worker image builds"
else
  fail "disposable worker image builds"
fi

# ---- Phase D: gateway configuration validates in its own image -----------
# The dedicated-mode probe needs a real HTTPS site without a public domain or
# a public CA, so it is the production Caddyfile plus the internal-CA global
# options. Same routes, same log directive, no second copy to drift.
{
  printf '{\n\tlocal_certs\n\tskip_install_trust\n}\n\n'
  cat "$CADDYFILE_ABS"
} >"$DEDICATED_CADDYFILE"

validate_caddyfile() { # $1=host caddyfile, $2=label
  if docker run --rm -v "$(hostpath "$1"):/etc/caddy/Caddyfile:ro" \
    --entrypoint caddy "$GW_IMAGE" validate --config /etc/caddy/Caddyfile \
    --adapter caddyfile >/dev/null 2>&1; then
    pass "Caddyfile validates inside gateway image [$2]"
  else
    fail "Caddyfile validates inside gateway image [$2]"
  fi
}
validate_caddyfile "$CADDYFILE_ABS" "production"
validate_caddyfile "$DEDICATED_CADDYFILE" "dedicated-probe"

# ---- Phase E: rendered production configuration --------------------------
# Every assertion for one combination is evaluated in a single python
# invocation against a single rendered config read from stdin, so no assertion
# can read a config a later render has already replaced, and a broken
# expression is a visible failure rather than a silently skipped one.
cat >"$CHECK" <<'PY'
"""Evaluate `description<TAB>expression` lines against a rendered Compose config.

Reads the config as JSON on stdin. Exits non-zero when any expression is
false, so the shell can rely on the exit status as well as the printed lines.
"""
import json
import sys

label = sys.argv[1]
cfg = json.load(sys.stdin)
failures = 0
for line in sys.argv[2:]:
    description, _, expression = line.partition("\t")
    try:
        ok = bool(eval(expression, {"cfg": cfg, "json": json}))
    except Exception as exc:  # noqa: BLE001 - a broken assertion is a failure
        ok = False
        description = f"{description} (assertion error: {type(exc).__name__})"
    print(f"{'PASS' if ok else 'FAIL'}: [{label}] {description}")
    failures += 0 if ok else 1
sys.exit(1 if failures else 0)
PY

compose() {
  docker compose -p "$PROJ" --env-file "$ENV_ARG" -f "$(hostpath "$PROD")" "$@"
}

# $1=label, $2=proxy mode (dedicated|existing), rest = extra compose files
# (must be last) and "description<TAB>expression" assertion lines.
run_checks() {
  local label="$1" proxy="$2"; shift 2
  local files=() assertions=() out
  while [ "$#" -gt 0 ]; do
    if [ "${1#-f}" = "$1" ]; then
      assertions+=("$1"); shift
    elif [ "$#" -lt 2 ]; then
      # A trailing -f with no file would silently drop a combination from the
      # contract instead of failing it.
      fail "malformed assertion list for $label (-f without a file)"
      return 0
    else
      files+=("$1" "$2"); shift 2
    fi
  done
  local json
  if ! json="$(compose "${files[@]}" config --format json 2>/dev/null)"; then
    fail "config renders: $label"
    return 0
  fi
  pass "config renders: $label"
  # hostpath: python3 may be a Windows interpreter that cannot open a POSIX path.
  if ! out="$(printf '%s' "$json" | python3 "$(hostpath "$CHECK")" "$label" "${assertions[@]}")"; then
    # Either an assertion failed or the checker never ran. Reporting nothing
    # here would let a broken checker look like a passing combination.
    if [ -z "$out" ]; then
      fail "assertion checker ran for $label"
      return 0
    fi
  fi
  while IFS= read -r line; do
    case "$line" in
      "PASS: "*) pass "${line#PASS: }" ;;
      "FAIL: "*) fail "${line#FAIL: }" ;;
    esac
  done <<<"$out"
}

# Assertions that hold in every combination: the deployment contract itself.
# Each is one array element of "description<TAB>expression". They are read with
# mapfile rather than command substitution because an assertion line contains
# spaces, and word splitting would turn one assertion into several broken ones.
common() {
  cat <<'EOF'
named volumes db-data/media-data/caddy-data	all(v in cfg.get('volumes',{}) for v in ('db-data','media-data','caddy-data'))
no bind driver_opts on prod volumes	all('driver_opts' not in v for v in cfg.get('volumes',{}).values())
every service bounds logs to 3x10m json-file	all(s.get('logging',{}).get('driver')=='json-file' and s['logging']['options'].get('max-size')=='10m' and s['logging']['options'].get('max-file')=='3' for s in cfg['services'].values())
backend probes /ready, not /health	any('/ready' in str(t) for t in cfg['services']['backend']['healthcheck']['test']) and not any("'/health'" in str(t) for t in cfg['services']['backend']['healthcheck']['test'])
backend readiness HTTP call is bounded inside the probe timeout	any('timeout=' in str(t) for t in cfg['services']['backend']['healthcheck']['test'])
worker probes the health CLI	any('worker.health' in str(t) for t in cfg['services']['worker']['healthcheck']['test'])
gateway probes the loopback web health asset	any('8081' in str(t) and 'web-health.txt' in str(t) for t in cfg['services']['gateway']['healthcheck']['test'])
probe cadence is 15s/5s/3/30s on backend, worker and gateway	all(cfg['services'][s]['healthcheck'].get(k)==v for s in ('backend','worker','gateway') for k,v in (('interval','15s'),('timeout','5s'),('retries',3),('start_period','30s')))
worker health deadlines are 120s idle and 3600s busy	str(cfg['services']['worker']['environment'].get('WORKER_HEALTH_IDLE_SECONDS'))=='120' and str(cfg['services']['worker']['environment'].get('WORKER_HEALTH_BUSY_SECONDS'))=='3600'
gateway mounts no media volume	not any('media-data' in str(v) for v in cfg['services']['gateway'].get('volumes',[]))
no docker socket is mounted anywhere	'/var/run/docker.sock' not in json.dumps(cfg)
media root stays the container-local volume mount	cfg['services']['worker']['environment'].get('MEDIA_ROOT')=='/media'
EOF
}

mapfile -t COMMON < <(common)

proxy() { # $1=proxy mode
  if [ "$1" = dedicated ]; then
    printf 'gateway publishes 80 and 443\tall(p in [str(q.get("published", q)) if isinstance(q, dict) else str(q) for q in cfg["services"]["gateway"].get("ports",[])] for p in ("80","443"))\n'
  else
    printf 'gateway HTTP stays loopback-bound\tany("127.0.0.1" in str(p) for p in cfg["services"]["gateway"].get("ports",[]))\n'
  fi
}

# The base pair asserts the alerting switches are OFF and the monitoring pair
# asserts they are ON: they are opposite halves of one contract, so each is
# checked only where it applies.
base() {
  cat <<'EOF'
base production sends no operational alerts	str(cfg['services']['worker']['environment'].get('MONITORING_ENABLED','false')).lower()!='true'
base production exposes no FCM credentials	'GOOGLE_APPLICATION_CREDENTIALS' not in cfg['services']['worker'].get('environment',{}) and 'FCM_ENABLED' not in cfg['services']['worker'].get('environment',{})
EOF
}

monitoring() {
  cat <<'EOF'
monitoring is enabled on the worker	str(cfg['services']['worker']['environment'].get('MONITORING_ENABLED')).lower()=='true'
real FCM delivery is enabled on the worker	str(cfg['services']['worker']['environment'].get('FCM_ENABLED')).lower()=='true'
credentials resolve from the mounted secret path	cfg['services']['worker']['environment'].get('GOOGLE_APPLICATION_CREDENTIALS')=='/run/secrets/firebase-credentials.json'
credential file is mounted as a compose secret	any(s.get('source')=='firebase_credentials' and s.get('target')=='firebase-credentials.json' for s in cfg['services']['worker'].get('secrets',[]))
the secret reads the operator host credential file	cfg.get('secrets',{}).get('firebase_credentials',{}).get('file','').endswith('fcm-dummy.json')
no credential value is inlined into the rendered environment	'service_account' not in json.dumps(cfg['services']['worker'].get('environment',{}))
EOF
}

mapfile -t BASE < <(base)
mapfile -t MONITORING_CHECKS < <(monitoring)

run_checks "base+existing-proxy" existing \
  -f "$(hostpath "$EXISTING")" \
  "${COMMON[@]}" "$(proxy existing)" "${BASE[@]}"
run_checks "base+dedicated" dedicated \
  -f "$(hostpath "$DEDICATED")" \
  "${COMMON[@]}" "$(proxy dedicated)" "${BASE[@]}"
run_checks "base+existing-proxy+monitoring" existing \
  -f "$(hostpath "$EXISTING")" -f "$(hostpath "$MONITORING")" \
  "${COMMON[@]}" "$(proxy existing)" "${MONITORING_CHECKS[@]}"
run_checks "base+dedicated+monitoring" dedicated \
  -f "$(hostpath "$DEDICATED")" -f "$(hostpath "$MONITORING")" \
  "${COMMON[@]}" "$(proxy dedicated)" "${MONITORING_CHECKS[@]}"

# The override is only safe if the operator must point it at a real file: an
# unset or empty host path must fail the render, never fall back to a default
# that does not exist.
if compose -f "$(hostpath "$EXISTING")" -f "$(hostpath "$MONITORING")" config >/dev/null 2>&1; then
  pass "monitoring override renders with a credential file"
else
  fail "monitoring override renders with a credential file"
fi
# Both required settings must fail the render, not boot: an unset credential
# path would mount nothing, and an unset project id crash-loops the worker.
EMPTY_ENV="$RUNDIR/no-credential.env"
grep -v '^FCM_CREDENTIALS_FILE=' "$SYNTH_ENV" >"$EMPTY_ENV"
if docker compose -p "$PROJ" --env-file "$(hostpath "$EMPTY_ENV")" \
  -f "$(hostpath "$PROD")" -f "$(hostpath "$EXISTING")" \
  -f "$(hostpath "$MONITORING")" config >/dev/null 2>&1; then
  fail "monitoring override refuses to render without a credential file"
else
  pass "monitoring override refuses to render without a credential file"
fi
NO_PROJECT_ENV="$RUNDIR/no-project.env"
grep -v '^FCM_PROJECT_ID=' "$SYNTH_ENV" >"$NO_PROJECT_ENV"
if docker compose -p "$PROJ" --env-file "$(hostpath "$NO_PROJECT_ENV")" \
  -f "$(hostpath "$PROD")" -f "$(hostpath "$EXISTING")" \
  -f "$(hostpath "$MONITORING")" config >/dev/null 2>&1; then
  fail "monitoring override refuses to render without a project id"
else
  pass "monitoring override refuses to render without a project id"
fi

# ---- Phase F: the mounted secret is present and read-only ----------------
# The rendered config says the secret is declared; only the container proves it
# is actually mounted read-only at the path the worker resolves. `compose run`
# resolves the worker image from IMAGE_TAG, which the synthetic env pins to this
# run's suffix, so this starts the image built in Phase C and nothing else.
#
# The mount must refuse a write from inside the container. The permission bits
# themselves are not asserted: a Compose secret is read-only by contract, and on
# a Windows host daemon the bind source is a file whose mode is synthesized
# rather than POSIX, so a mode check would assert the host's file system instead
# of the deployment contract.
if compose -f "$(hostpath "$EXISTING")" -f "$(hostpath "$MONITORING")" \
  run --rm --no-deps --entrypoint /bin/sh worker -c \
  'test -r /run/secrets/firebase-credentials.json || exit 1
   (echo tampered > /run/secrets/firebase-credentials.json) >/dev/null 2>&1 && exit 2
   exit 0' >/dev/null 2>&1; then
  pass "firebase credentials are readable but not writable in the worker"
else
  fail "firebase credentials are readable but not writable in the worker"
fi

# ---- Phase G: real FCM configuration is proven, never exercised -----------
if docker run --rm --network none --entrypoint .venv/bin/python "$WORKER_IMAGE" \
  -c "import firebase_admin" >/dev/null 2>&1; then
  pass "worker image can import firebase_admin"
else
  fail "worker image can import firebase_admin"
fi

# Application Default Credentials are resolved lazily by the SDK, so a mounted
# but unusable credential file does not fail construction — it fails the first
# send. What must hold is that the failure is loud and typed rather than a
# silent success, because a send reported as delivered would drop the alert.
# --network none proves the failure cannot be a real provider round trip.
# Project identity, by contrast, IS validated at construction: FCM addresses by
# project, so a deployment that cannot name one must not boot. Asserted here
# against the real built image, because this is the claim the runbook makes.
docker run --rm --network none \
  -v "$(hostpath "$BAD_SECRET"):/run/secrets/firebase-credentials.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/firebase-credentials.json \
  --entrypoint .venv/bin/python "$WORKER_IMAGE" -c '
from dojo.adapters.fcm import FcmNotifier

for value in (None, "", "   "):
    try:
        FcmNotifier(project_id=value)
    except RuntimeError as exc:
        print("OUTCOME raised", type(exc).__name__, "|", exc)
    else:
        print("OUTCOME built", value)
' >"$PROJECT_LOG" 2>&1 || true
if [ "$(grep -c '^OUTCOME raised RuntimeError | FCM is enabled but no Firebase project id' "$PROJECT_LOG")" = "3" ]; then
  pass "every missing project id is rejected at construction"
else
  fail "every missing project id is rejected at construction"
fi
if grep -q "GOOGLE_APPLICATION_CREDENTIALS\|BEGIN PRIVATE KEY\|private_key" "$PROJECT_LOG"; then
  fail "the project id failure leaks no credential text"
else
  pass "the project id failure leaks no credential text"
fi

# The credential FILE is not validated at construction: the SDK resolves it
# lazily. What must hold is that the failure is loud and typed rather than a
# silent success, because a send reported as delivered would drop the alert.
# --network none proves the failure cannot be a real provider round trip.
docker run --rm --network none \
  -v "$(hostpath "$BAD_SECRET"):/run/secrets/firebase-credentials.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/firebase-credentials.json \
  -e FCM_PROJECT_ID=dojo-verify-not-a-project \
  --entrypoint .venv/bin/python "$WORKER_IMAGE" -c '
from dojo import Notification
from dojo.adapters.fcm import FcmNotifier

notifier = FcmNotifier(project_id="dojo-verify-not-a-project")
alert = Notification(
    title="Disk alanı azalıyor",
    body="media hedefinde boş alan oranı düşük.",
    data={"type": "operational_alert", "alert_id": "verify", "kind": "disk.low"},
)
try:
    result = notifier.send(alert, ["verify-token"])
except Exception as exc:  # noqa: BLE001
    print("OUTCOME raised", type(exc).__name__)
else:
    print("OUTCOME result", result)
' >"$SEND_LOG" 2>&1 || true
if grep -q "^OUTCOME raised " "$SEND_LOG"; then
  pass "an unusable credential fails the send instead of reporting success"
else
  fail "an unusable credential fails the send instead of reporting success"
fi
if grep -qE "^OUTCOME raised (DefaultCredentialsError|ValueError)" "$SEND_LOG"; then
  pass "the credential failure is a typed credential error"
else
  fail "the credential failure is a typed credential error"
fi
if grep -q "verify-token" "$SEND_LOG"; then
  fail "no push token appears in the credential failure output"
else
  pass "no push token appears in the credential failure output"
fi

# ---- Phase H: gateway runtime, both production modes ----------------------
if docker network create "$NET" >/dev/null 2>&1; then
  pass "disposable network created"
else
  fail "disposable network created"
fi
if docker run -d --name "$BACKEND" --network "$NET" --network-alias backend \
  -v "$(hostpath "$STUB"):/stub.py:ro" --entrypoint .venv/bin/python \
  "$WORKER_IMAGE" /stub.py >/dev/null 2>&1; then
  pass "disposable API stand-in starts"
else
  fail "disposable API stand-in starts"
fi

# PUBLIC_ARGS and PUBLIC_URL describe the production mode under test: the
# public site is reached with the same address and Host an upstream would use,
# and each request appends one path. Keeping them in variables rather than
# positional arguments means the call sites cannot order the curl flags and the
# URL wrongly, which a wrong order silently turns into a 000.
PUBLIC_ARGS=()
PUBLIC_URL=""
# $1=container, $2=path on the public site
http_public() {
  docker exec "$1" curl -s -o /dev/null -w '%{http_code}' \
    "${PUBLIC_ARGS[@]}" "${PUBLIC_URL}${2}" 2>/dev/null || echo "000"
}
# $1=container, $2=path on the loopback probe listener
http_probe() {
  docker exec "$1" curl -s -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1:8081${2}" 2>/dev/null || echo "000"
}
# The hosted monitor keys on the response BODY, so the body is what has to be
# asserted: a status-only check passes the SPA fallback, which answers 200 with
# index.html. Command substitution strips a trailing newline, so this compares
# the served keyword itself, not its line ending.
# $1=container, $2=path on the public site
body_public() {
  docker exec "$1" curl -s "${PUBLIC_ARGS[@]}" "${PUBLIC_URL}${2}" 2>/dev/null || true
}
# $1=container, $2=path on the loopback probe listener
body_probe() {
  docker exec "$1" curl -s "http://127.0.0.1:8081${2}" 2>/dev/null || true
}

wait_for_probe() { # $1=container
  local i
  for i in $(seq 1 30); do
    if [ "$(http_probe "$1" /web-health.txt)" = "200" ]; then return 0; fi
    sleep 1
  done
  return 1
}

start_gateway() { # $1=container, $2=host caddyfile, $3=site address
  docker run -d --name "$1" --network "$NET" \
    --tmpfs /data --tmpfs /config \
    -e "SITE_ADDRESS=$3" -e TRUSTED_PROXIES=private_ranges \
    -v "$(hostpath "$2"):/etc/caddy/Caddyfile:ro" \
    "$GW_IMAGE" >/dev/null 2>&1
}

# Exercises one production mode end to end against the real Caddyfile: the
# public site route and the loopback probe route must both serve the built
# asset, a missing asset must be a 404 rather than the SPA, and a stopped API
# must fail readiness without touching web health.
exercise_mode() { # $1=label, $2=container
  local label="$1" container="$2"
  if wait_for_probe "$container"; then
    pass "[$label] loopback probe route serves the built asset"
  else
    fail "[$label] loopback probe route serves the built asset"
    return 0
  fi
  if [ "$(http_public "$container" /web-health.txt)" = "200" ]; then
    pass "[$label] public route serves the built asset"
  else
    fail "[$label] public route serves the built asset"
  fi
  if [ "$(http_probe "$container" /not-a-route)" = "404" ]; then
    pass "[$label] probe listener answers 404 outside the asset"
  else
    fail "[$label] probe listener answers 404 outside the asset"
  fi

  # The two strings runbook §6 tells the operator to configure as the expected
  # body, served through the real gateway. Without these the whole deployment
  # can pass on status codes while the external check keys on something else.
  if [ "$(body_public "$container" /web-health.txt)" = "dojo-web-ok" ]; then
    pass "[$label] public web-health body is dojo-web-ok"
  else
    fail "[$label] public web-health body is dojo-web-ok"
  fi
  if [ "$(body_probe "$container" /web-health.txt)" = "dojo-web-ok" ]; then
    pass "[$label] probe web-health body is dojo-web-ok"
  else
    fail "[$label] probe web-health body is dojo-web-ok"
  fi
  if [ "$(body_public "$container" /ready)" = '{"status":"ok"}' ]; then
    pass "[$label] readiness body is the documented status object"
  else
    fail "[$label] readiness body is the documented status object"
  fi

  # API down, asset still in place. The three facts the brief asks for are
  # asserted here, in this order, with the asset present: web health must keep
  # answering 200, readiness must fail, and readiness must recover afterwards.
  docker stop "$BACKEND" >/dev/null 2>&1 || true
  if [ "$(http_public "$container" /web-health.txt)" = "200" ] \
    && [ "$(http_probe "$container" /web-health.txt)" = "200" ]; then
    pass "[$label] web health still succeeds while the API is down"
  else
    fail "[$label] web health still succeeds while the API is down"
  fi
  if [ "$(http_public "$container" /ready)" != "200" ]; then
    pass "[$label] readiness fails while the API is down"
  else
    fail "[$label] readiness fails while the API is down"
  fi
  docker start "$BACKEND" >/dev/null 2>&1 || true
  if wait_for_public "$container" /ready; then
    pass "[$label] readiness recovers after the API returns"
  else
    fail "[$label] readiness recovers after the API returns"
  fi

  # Only now, with readiness proven in both directions, is the missing-asset
  # case checked. Removing the asset earlier would have made "web health still
  # succeeds" assert a 404.
  if docker exec "$container" rm -f /srv/web-health.txt >/dev/null 2>&1 \
    && [ "$(http_public "$container" /web-health.txt)" = "404" ] \
    && [ "$(http_probe "$container" /web-health.txt)" = "404" ]; then
    pass "[$label] removed health asset is 404, not the SPA"
  else
    fail "[$label] removed health asset is 404, not the SPA"
  fi
}

# Dedicated-domain mode: Caddy owns TLS for a public site name. The internal
# CA keeps the check offline, and HTTP must redirect to HTTPS so the hosted
# monitor is pointed at the https URL.
if start_gateway "$GW_DEDICATED" "$DEDICATED_CADDYFILE" monitoring.verify.test; then
  pass "dedicated-mode gateway starts"
else
  fail "dedicated-mode gateway starts"
fi
PUBLIC_ARGS=(--resolve monitoring.verify.test:443:127.0.0.1 --insecure)
PUBLIC_URL=https://monitoring.verify.test
# The dedicated site needs a moment to issue its internal certificate before the
# first public request; the loopback probe answers before that is true.
wait_for_public() { # $1=container, $2=path
  local i
  for i in $(seq 1 30); do
    if [ "$(http_public "$1" "$2")" = "200" ]; then return 0; fi
    sleep 1
  done
  return 1
}
if wait_for_public "$GW_DEDICATED" /ready; then
  pass "[dedicated] API readiness is routed to the backend"
else
  fail "[dedicated] API readiness is routed to the backend"
fi
exercise_mode "dedicated" "$GW_DEDICATED"
# Plain HTTP to a domain Caddy owns must redirect, not serve: that is why the
# hosted monitor has to be pointed at the https URL. Checked with a full URL of
# its own rather than through http_public, which builds the https one.
if [ "$(docker exec "$GW_DEDICATED" curl -s -o /dev/null -w '%{http_code}' \
  --resolve monitoring.verify.test:80:127.0.0.1 \
  http://monitoring.verify.test/web-health.txt 2>/dev/null || echo 000)" = "308" ]; then
  pass "[dedicated] plain HTTP redirects to HTTPS"
else
  fail "[dedicated] plain HTTP redirects to HTTPS"
fi

# Existing-proxy mode: plain HTTP on the loopback port, upstream owns TLS.
if start_gateway "$GW_EXISTING" "$CADDYFILE_ABS" ":80"; then
  pass "existing-proxy gateway starts"
else
  fail "existing-proxy gateway starts"
fi
PUBLIC_ARGS=(-H "Host: deploy.example.test")
PUBLIC_URL=http://127.0.0.1
if wait_for_public "$GW_EXISTING" /ready; then
  pass "[existing-proxy] API readiness is routed to the backend"
else
  fail "[existing-proxy] API readiness is routed to the backend"
fi
exercise_mode "existing-proxy" "$GW_EXISTING"

# ---- Phase I: gateway access logs are safe JSON --------------------------
# Synthetic marker values that must never reach a log line: a signed artifact
# token in the path, a query signature, a bearer token header, a request cookie
# and — the one that cannot be deleted by the Caddyfile — a session cookie the
# API sets on its RESPONSE. Caddy emits resp_headers on every access record, so
# the response side is only safe because Caddy redacts credential header values;
# this phase is what proves it still does.
docker exec "$GW_EXISTING" sh -c 'echo ok > /srv/web-health.txt' >/dev/null 2>&1 || true
# The token, the query signature and both header values are synthetic markers
# that must not survive into a log line. PUBLIC_ARGS already carries the Host
# header the upstream proxy would set.
curl_in_container() {
  docker exec "$GW_EXISTING" curl -s -o /dev/null \
    "${PUBLIC_ARGS[@]}" "$@" 2>/dev/null || true
}
curl_in_container "${PUBLIC_URL}/pub/VERIFYMONTOKEN?sig=VERIFYMONSIG" \
  -H "Authorization: Bearer VERIFYMONBEARER" \
  -H "Cookie: session=VERIFYMONCOOKIE"
curl_in_container "${PUBLIC_URL}/web-health.txt"
# Routed to the API stand-in, whose every response carries Set-Cookie.
curl_in_container "${PUBLIC_URL}/ready"
docker logs "$GW_EXISTING" >"$LOGFILE" 2>&1 || true

if python3 - "$(hostpath "$LOGFILE")" <<'PY'
import json
import sys

records = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
access = [r for r in records if r.get("msg") == "handled request"]
assert access, "no JSON access log records were emitted"
for record in access:
    assert record["request"].get("method"), record
    assert isinstance(record.get("status"), int), record
    assert isinstance(record.get("duration"), (int, float)), record
    # The two request parts that can carry a secret are gone, not masked.
    assert "uri" not in record["request"], record
    assert "headers" not in record["request"], record
    # The response side is NOT deleted by the Caddyfile: Caddy always emits
    # resp_headers, and the only thing keeping the session cookie out of this
    # log is its own redaction of credential header values. The field has to be
    # present for that to be a real claim — a gateway that stopped logging it
    # would satisfy a marker-only check vacuously — and its values must never
    # contain the marker.
    with_response_headers = [
        r for r in access
        if any("resp_headers" in field for field in r)
    ]
    assert with_response_headers, "no access record carries resp_headers at all"
    assert any(
        any("set-cookie" in str(name).lower() for name in record["resp_headers"])
        for record in with_response_headers
    ), "no logged Set-Cookie response header was observed"
    for record in with_response_headers:
        for name, values in record["resp_headers"].items():
            for value in values if isinstance(values, list) else [values]:
                assert "VERIFYMONSESSION" not in str(value), (name, record)
PY
then
  pass "gateway access logs are JSON with method, status, timing and no URI or headers"
else
  fail "gateway access logs are JSON with method, status, timing and no URI or headers"
fi

if python3 - "$(hostpath "$LOGFILE")" <<'PY'
import json
import sys

records = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
access = [r for r in records if r.get("msg") == "handled request"]
observed = 0
for record in access:
    for name, values in record.get("resp_headers", {}).items():
        if any(cred in str(name).lower() for cred in ("cookie", "authorization")):
            observed += 1
            for value in values if isinstance(values, list) else [values]:
                # REDACTED is Caddy's own replacement for a credential header
                # value. Anything else is the value itself, in the log.
                assert str(value).strip() == "REDACTED", (name, value)
# Never vacuous: the check above must have had something to reject.
assert observed, "no credential response header was observed in the access log"
PY
then
  pass "credential response headers are redacted, not logged verbatim"
else
  fail "credential response headers are redacted, not logged verbatim"
fi

for marker in VERIFYMONTOKEN VERIFYMONSIG VERIFYMONBEARER VERIFYMONCOOKIE VERIFYMONSESSION; do
  if grep -q "$marker" "$LOGFILE"; then
    fail "gateway logs omit synthetic value: $marker"
  else
    pass "gateway logs omit synthetic value: $marker"
  fi
done

echo "verify-monitoring: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
