# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app/services/api
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY services/api/pyproject.toml services/api/uv.lock ./
COPY services/api/src ./src
COPY packages/sdk-python/pyproject.toml /app/packages/sdk-python/pyproject.toml
COPY packages/sdk-python/src /app/packages/sdk-python/src
RUN uv sync --frozen --no-dev --no-editable

COPY services/api/alembic.ini ./alembic.ini
COPY services/api/migrations ./migrations

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app/services/api
ENV AXIS_ENV=production \
    PATH="/app/services/api/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 axis \
    && useradd --system --uid 10001 --gid axis --home-dir /app --shell /usr/sbin/nologin axis

COPY --from=builder --chown=axis:axis /app/services/api /app/services/api

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["sh", "-c", "exec uvicorn axis_api.main:create_app --factory --host 0.0.0.0 --port 8000"]
