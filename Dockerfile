# syntax=docker/dockerfile:1.7
#
# Multi-arch (linux/amd64 + linux/arm64) image for the invoice app.
#   docker build --target prod -t invoice-app .     # production (default target)
#   docker build --target dev  -t invoice-app:dev . # tests / auto-reload dev server

ARG PYTHON_IMAGE=python:3.12-slim

# ---------------------------------------------------------------------------
# base: Python + WeasyPrint system libraries (Pango, PangoFT2, HarfBuzz subset).
# Cairo is not required by modern WeasyPrint.
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# ---------------------------------------------------------------------------
# dev: dev/test dependencies + poppler-utils (pdftoppm). Source is bind-mounted.
# ---------------------------------------------------------------------------
FROM base AS dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-dev.txt

# ---------------------------------------------------------------------------
# prod: runtime dependencies only, non-root user, healthcheck.
# ---------------------------------------------------------------------------
FROM base AS prod

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY app ./app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
USER app

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 2 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-*}\""]
