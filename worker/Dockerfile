FROM ghcr.io/astral-sh/uv:0.8.4 AS uv

FROM python:3.12.14-slim

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY dojo-core ./dojo-core
COPY worker ./worker

RUN uv sync --frozen --no-dev --package worker

CMD [".venv/bin/python", "-m", "worker.main"]
