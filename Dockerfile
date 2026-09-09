FROM python:3.12.14-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/app/.venv/bin:${PATH}"

RUN python -m pip install --no-cache-dir uv==0.12.11 \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /nonexistent --no-create-home app

WORKDIR /opt/app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
RUN chown app:app /opt/app

FROM base AS runtime

ENV UV_CACHE_DIR=/tmp/uv-cache

COPY --chown=app:app . .
USER app

FROM base AS test

RUN uv sync --frozen
ENV UV_CACHE_DIR=/tmp/uv-cache
COPY --chown=app:app . .
USER app
