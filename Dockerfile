# Multi-arch (linux/amd64 + linux/arm64) image for the invoice app.
# Plain Dockerfile syntax only (no BuildKit-only features), so it also builds on hosts that use the
# classic builder — e.g. Cloud Build behind `gcloud run deploy --source`.
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
    PIP_ROOT_USER_ACTION=ignore \
    PIP_NO_CACHE_DIR=1

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
RUN pip install -r requirements-dev.txt

# ---------------------------------------------------------------------------
# prod: runtime dependencies only, non-root user, healthcheck.
# ---------------------------------------------------------------------------
FROM base AS prod

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
USER app

# The app user has no home directory; give fontconfig a writable cache location.
ENV PORT=8000 \
    XDG_CACHE_HOME=/tmp/.cache
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)" || exit 1

# One worker (owner decision): the rate limiter and the render semaphore live in memory, so a
# single process keeps them exact (10 PDFs/min/IP, 2 renders at a time).
# --proxy-headers: the client IP comes from X-Forwarded-For only when the request arrives from an
# address in FORWARDED_ALLOW_IPS. With compose.yml the app is reachable only from Caddy on a private
# network, so "*" trusts nothing else; Cloud Run's front end also needs "*".
# --no-access-log: the app writes its own access log (never bodies or item contents).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-*}\" --no-access-log"]
