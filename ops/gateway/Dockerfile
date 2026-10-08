# Gateway image: Caddy serving the built frontend (vite build output).
# Build from the repo root: docker build -f ops/gateway/Dockerfile .
# Raw media volumes are deliberately NOT mounted here; artifact bytes flow
# through the backend proxy, never from gateway disk.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Pinned to an exact version, not the floating `caddy:2-alpine`: the access-log
# filter in the Caddyfile only deletes the REQUEST uri and headers, so whether
# the RESPONSE headers of a paired session are redacted is decided by Caddy's
# own credential-header handling. `ops/verify-monitoring.sh` asserts the
# redaction against the built image, and a floating tag would let a future
# default change move under that assertion.
FROM caddy:2.11.4-alpine

COPY ops/gateway/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-build /web/dist /srv

EXPOSE 80 443
