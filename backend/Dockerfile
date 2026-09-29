FROM ghcr.io/astral-sh/uv:0.8.4 AS uv

FROM python:3.12.14-slim

# FFmpeg IS executed on backend request paths: completing an upload runs
# ffprobe/ffmpeg via dojo.adapters.media.PillowFFmpegProcessor, so the
# backend image ships the same media tooling as the worker (which renders).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY dojo-core ./dojo-core
COPY backend ./backend

RUN uv sync --frozen --no-dev --package backend

EXPOSE 8000
# Uvicorn --proxy-headers stays DISABLED on purpose: forwarded client/scheme
# headers are normalized by the single ASGI layer in backend/proxy.py, which
# trusts them only from TRUSTED_PROXIES (the gateway container network).
# Enabling uvicorn proxy handling too would create two competing trust layers.
# Gateway->backend trust (here) is separate from upstream-proxy->gateway trust
# (Caddy trusted_proxies in ops/gateway/Caddyfile).
CMD [".venv/bin/python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
