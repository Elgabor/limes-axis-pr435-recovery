# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app/services/worker
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# The worker depends on the API package via a local path source
# (tool.uv.sources), so the API sources must be present in the build context
# for `uv sync` to resolve and install limes-axis-api.
COPY services/api /app/services/api
COPY packages/sdk-python/pyproject.toml /app/packages/sdk-python/pyproject.toml
COPY packages/sdk-python/src /app/packages/sdk-python/src
COPY services/worker/pyproject.toml services/worker/uv.lock ./
COPY services/worker/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app/services/worker
ENV AXIS_ENV=production \
    PATH="/app/services/worker/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 axis \
    && useradd --system --uid 10001 --gid axis --home-dir /app --shell /usr/sbin/nologin axis

COPY --from=builder --chown=axis:axis /app/services/worker /app/services/worker

USER 10001

CMD ["python", "-m", "axis_worker"]
