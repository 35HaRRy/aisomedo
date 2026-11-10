# Aisomedo: package-only shared HTTPS ingress

No checkout or image build is needed on the server. Aisomedo's existing CI builds
and publishes images and delivers a release bundle. New bundles also carry
`gateway-aisomedo.caddy` and `gateway-adapter.yml`; these are Aisomedo-owned, not
declarations in the independent gateway repository. Legacy bundles remain valid.

The existing inner Caddy continues serving Aisomedo web/backend. Only independent
shared Caddy publishes public 80/443. DB/backend/worker networks, images, data and
the `dojo-prod` project name remain unchanged during ingress cutover.

## Prepare once (Linux)

Use the existing installation's `DEPLOY_ROOT`, env and registry credentials.
Examples below assume `/srv/aisomedo`; **do not relocate/rename an existing install**.
The existing release helper requires Python 3; this is deployment tooling, not
application source or a build runtime. Ordinary deploys remain automatic via CI.

1. Pause automatic production deploys and take the normal DB/media backup. Save
   the old state and full dedicated-mode command. Keep all volume/certificate names.
2. Obtain a **new-format** `release-SHA` artifact from the existing CI pipeline,
   unpacked as `/srv/aisomedo/incoming-SHA`. Do not run `git clone` or `docker build`.
   Keep the current deployment running until routing preparation is validated.
3. Install the app-owned gateway files at stable paths (not disposable releases):

   ```sh
   install -d -m 700 /srv/aisomedo/config/gateway
   cp /srv/aisomedo/incoming-SHA/gateway-aisomedo.caddy /srv/aisomedo/config/gateway/
   cp /srv/aisomedo/incoming-SHA/gateway-adapter.yml /srv/aisomedo/config/gateway/
   docker network create gateway-aisomedo
   ```

   Inspect/reuse the network if it exists. Only the inner and shared gateways join
   it; DB/backend/worker do not. Add to the shared gateway's private env file:

   ```dotenv
   AISOMEDO_DOMAIN=existing-aisomedo.example.com
   AISOMEDO_GATEWAY_CONFIG=/srv/aisomedo/config/gateway/gateway-aisomedo.caddy
   ```

   Keep the current public hostname, cookies and Meta callback URLs unchanged.
   Add `-f /srv/aisomedo/config/gateway/gateway-adapter.yml` to the independent
   gateway's complete Compose file list. Its generic package/base comes first.

## Repackage the currently running image digests (no checkout)

The new artifact may contain newer application images; ingress cutover must not
accidentally upgrade backend/schema. Create a baseline bundle with the **currently
recorded image digests** and new runtime/deployment files. Example, adapt paths:

```sh
python3 - /srv/aisomedo /srv/aisomedo/incoming-SHA /srv/aisomedo/baseline-SHA <<'PY'
import json, subprocess, sys
from pathlib import Path
root, incoming, output = map(Path, sys.argv[1:])
state = json.loads((root / 'current.json').read_text())
old = json.loads((root / 'releases' / state['sha'] / 'release.json').read_text())
new = json.loads((incoming / 'release.json').read_text())
assert new['sha'] != state['sha'], 'Use a new release SHA, not the existing immutable bundle'
command = [sys.executable, str(incoming / 'deploy.py'), 'bundle', '--sha', new['sha']]
for service in ('backend', 'worker', 'gateway'):
    command += ['--' + service, old['images'][service]]
subprocess.run(command + ['--output', str(output)], check=True)
PY
```

`baseline-SHA` must not already exist. The downloaded deploy helper can repackage
its own flat bundle, so application source is not needed. Keep this baseline and
the original release/state for rollback. Validate shared Caddy with all application
adapters before taking public ports away from the old ingress.

## Cut over (brief ingress outage)

Recreate **only** the inner gateway with the baseline's exact image override:

```sh
docker compose --env-file /srv/aisomedo/config/production.env -p dojo-prod \
  -f /srv/aisomedo/baseline-SHA/docker-compose.prod.yml \
  -f /srv/aisomedo/baseline-SHA/docker-compose.shared-gateway.yml \
  -f /srv/aisomedo/baseline-SHA/images.json \
  up -d --no-build --no-deps --wait gateway
```

Do not combine dedicated/existing-proxy mode files with shared-gateway. This mode
has no host ports. Keep DB/backend/worker running. Start the independent shared
gateway, then check public HTTPS `/ready`, `/web-health.txt`, pairing, live updates
and signed media. Certificates for the new ingress live in its own persistent
volumes; the old inner Caddy volume is retained for rollback.

Once HTTPS is healthy, adopt the new baseline mode before resuming CI:

```sh
ROOT=/srv/aisomedo
BACKUP="$ROOT/current.before-shared-gateway.$(date +%s).json"
mv "$ROOT/current.json" "$BACKUP"
python3 "$ROOT/baseline-SHA/deploy.py" adopt \
  --release "$ROOT/baseline-SHA" --root "$ROOT" \
  --mode shared-gateway --origin https://existing-aisomedo.example.com
```

If adoption fails, restore `$BACKUP` to `current.json` and keep automatic deploys
paused. Do not hand-edit state SHA/mode. In GitHub production variables set
`DEPLOY_MODE=shared-gateway`, then resume automatic releases. The release helper
and CI both support the mode; recovery uses its recorded mode and image digests.

## Rollback and subsequent updates

If initial cutover fails, stop the independent gateway to release 80/443, recreate
only the inner gateway with the saved dedicated-mode command and original image
override, restore the previous state if changed, and verify HTTPS. Never delete
volumes, run `down -v`, rename `dojo-prod`, or silently change DB/network rules.

Normal Aisomedo releases do not restart shared ingress. Its site/adapter are shipped
with releases but activated independently at stable config paths; routing changes
require shared Caddy validate/reload. Keep the complete gateway adapter list and
follow its guide's warning about replacing a single-file bind mount atomically.

Checks: `python -m pytest ops/tests/test_deploy.py ops/tests/test_shared_gateway.py -q`.
