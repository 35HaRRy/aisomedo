# Gateway image: Caddy serving the built frontend (vite build output).
# Build from the repo root: docker build -f ops/gateway/Dockerfile .
# Raw media volumes are deliberately NOT mounted here; artifact bytes flow
# through the backend proxy, never from gateway disk.
FROM node:22-alpine AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM caddy:2-alpine

COPY ops/gateway/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-build /web/dist /srv

EXPOSE 80 443
