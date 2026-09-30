# syntax=docker/dockerfile:1.7
# FORGE backend image (API, workers, demo agents, CLI). Build context: ./backend
#   docker build -t forge-backend .
ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.12.17 AS uv

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd --system --gid 10001 forge \
    && useradd --system --uid 10001 --gid forge --home-dir /app --shell /usr/sbin/nologin forge

WORKDIR /app

# 1. Dependencies (cached layer: only invalidated when pyproject/uv.lock change)
COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --python "$(which python3)"

# 2. Application code
COPY alembic.ini ./
COPY alembic ./alembic
COPY forge ./forge
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --python "$(which python3)"
COPY docker/entrypoint.sh /usr/local/bin/forge-entrypoint
RUN chmod 0755 /usr/local/bin/forge-entrypoint \
    && python -m compileall -q forge \
    && chown -R forge:forge /app

USER forge
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/forge-entrypoint"]
CMD ["api"]
