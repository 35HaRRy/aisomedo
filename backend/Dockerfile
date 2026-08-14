FROM ghcr.io/astral-sh/uv:0.8.4 AS uv

FROM python:3.12.14-slim

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY dojo-core ./dojo-core
COPY backend ./backend

RUN uv sync --frozen --no-dev --package backend

EXPOSE 8000
CMD [".venv/bin/python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
