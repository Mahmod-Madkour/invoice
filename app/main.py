"""Application factory: routes, static files, middleware, error handlers.

Run with:  uvicorn app.main:app
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
import sys
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.limits import BodySizeLimitMiddleware, RenderSlots, SlidingWindowRateLimiter
from app.api.routes import WEB_DIR, router
from app.api.schemas import (
    MSG_BAD_REQUEST,
    TYPE_ERROR_MESSAGES,
    ErrorResponse,
    FieldError,
    InvoiceValidationError,
    error_content,
)
from app.config import MAX_BODY_BYTES, RATE_LIMIT_WINDOW_SECONDS, RENDER_SLOT_TIMEOUT_SECONDS, Settings, get_settings
from app.pdf.renderer import ASSETS_DIR, InvoicePdfRenderer

ACCESS_LOG = logging.getLogger("app.access")
MSG_AUTH_REQUIRED = "كلمة المرور مطلوبة"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'"
)
# Only when ENABLE_API_DOCS=true (development): Swagger UI / ReDoc need their CDN bundles and inline scripts.
DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "worker-src blob:; frame-ancestors 'none'"
)
DOCS_PATHS = ("/docs", "/redoc")


# --------------------------------------------------------------------------- middleware (pure ASGI)


class AccessLogMiddleware:
    """One line per request: method, path, status, duration, item count. Never bodies or item contents."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500
        state = scope.setdefault("state", {})

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            ACCESS_LOG.info(
                "%s %s %s %.0fms items=%s",
                scope["method"],
                scope["path"],
                status,
                (time.perf_counter() - started) * 1000,
                state.get("item_count", "-"),
            )


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, docs_enabled: bool) -> None:
        self.app = app
        self.docs_enabled = docs_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        relaxed = self.docs_enabled and scope["path"].startswith(DOCS_PATHS)
        extra = [
            (b"content-security-policy", (DOCS_CONTENT_SECURITY_POLICY if relaxed else CONTENT_SECURITY_POLICY).encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
        ]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {key.lower() for key, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [h for h in extra if h[0] not in present]
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BasicAuthMiddleware:
    """Optional HTTP Basic Auth (any username, APP_PASSWORD as password). /healthz stays open."""

    def __init__(self, app: ASGIApp, password: str) -> None:
        self.app = app
        self.password = password.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz" or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            error_content(MSG_AUTH_REQUIRED),
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="invoice", charset="UTF-8"'},
        )
        await response(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        header = dict(scope["headers"]).get(b"authorization", b"")
        scheme, _, encoded = header.partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            _, _, password = base64.b64decode(encoded, validate=True).partition(b":")
        except (binascii.Error, ValueError):
            return False
        return secrets.compare_digest(password, self.password)


# --------------------------------------------------------------------------- error handlers


async def invoice_validation_handler(request: Request, exc: InvoiceValidationError) -> JSONResponse:
    return JSONResponse(ErrorResponse(errors=exc.errors).model_dump(), status_code=422)


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Map Pydantic shape errors to the structured format — without echoing the input back."""
    errors: list[FieldError] = []
    for error in exc.errors():
        loc = [part for part in error.get("loc", ()) if part != "body"]
        if len(loc) == 3 and loc[0] == "items" and isinstance(loc[1], int):
            field = str(loc[2])
            errors.append(FieldError(row=loc[1] + 1, field=field, message=TYPE_ERROR_MESSAGES.get(field, MSG_BAD_REQUEST)))
        elif len(loc) == 2 and loc[0] == "items" and isinstance(loc[1], int):
            errors.append(FieldError(row=loc[1] + 1, field=None, message=MSG_BAD_REQUEST))
        elif len(loc) == 1 and loc[0] == "date":
            errors.append(FieldError(row=None, field="date", message=TYPE_ERROR_MESSAGES["date"]))
        else:
            errors.append(FieldError(row=None, field=None, message=MSG_BAD_REQUEST))
    unique = list({(e.row, e.field, e.message): e for e in errors}.values())
    return JSONResponse(ErrorResponse(errors=unique).model_dump(), status_code=422)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(error_content(str(exc.detail)), status_code=exc.status_code, headers=exc.headers)


# --------------------------------------------------------------------------- factory


def configure_logging(level: str) -> None:
    logger = logging.getLogger("app")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False


def create_app(settings: Settings | None = None, *, render_slot_timeout: float = RENDER_SLOT_TIMEOUT_SECONDS) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    docs = settings.enable_api_docs

    app = FastAPI(
        title="Arabic invoice PDF generator",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute, RATE_LIMIT_WINDOW_SECONDS)
    app.state.render_slots = RenderSlots(settings.max_concurrent_renders, render_slot_timeout)
    app.state.renderer = InvoicePdfRenderer()

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.mount("/fonts", StaticFiles(directory=ASSETS_DIR / "fonts"), name="fonts")

    app.add_exception_handler(InvoiceValidationError, invoice_validation_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Added innermost first; the last one added runs first.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    password = settings.app_password.get_secret_value()
    if password:
        app.add_middleware(BasicAuthMiddleware, password=password)
    app.add_middleware(SecurityHeadersMiddleware, docs_enabled=docs)
    app.add_middleware(AccessLogMiddleware)
    return app


app = create_app()
