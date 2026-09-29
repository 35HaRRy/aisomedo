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
CMD [".venv/bin/python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
