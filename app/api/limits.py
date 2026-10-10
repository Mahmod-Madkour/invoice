"""Resource limits for the public endpoint (spec §11): body size, rate limit, render concurrency.

All state is in memory and per process (no external dependency).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.schemas import error_content

MSG_BODY_TOO_LARGE = "حجم الطلب أكبر من الحد المسموح"
MSG_RATE_LIMITED = "عدد الطلبات كبير، حاول مرة أخرى بعد دقيقة"
MSG_BUSY = "الخادم مشغول، حاول مرة أخرى بعد قليل"


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_bytes`` with 413.

    Checks the declared Content-Length up front and also counts the bytes actually received,
    so a chunked request without Content-Length cannot get around the limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for key, value in scope["headers"]:
            if key == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = self.max_bytes + 1
                if declared > self.max_bytes:
                    await _reject(scope, receive, send, self.app)
                    return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(status_code=413, detail=MSG_BODY_TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)


async def _reject(scope: Scope, receive: Receive, send: Send, app: ASGIApp) -> None:
    response = JSONResponse(error_content(MSG_BODY_TOO_LARGE), status_code=413)
    await response(scope, receive, send)


class SlidingWindowRateLimiter:
    """At most ``limit`` hits per ``window`` seconds per key (client IP)."""

    _PURGE_EVERY = 1024

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str) -> float:
        """Record a hit. Returns 0 if allowed, else the seconds until the next hit is allowed."""
        now = self._clock()
        cutoff = now - self.window
        with self._lock:
            self._calls += 1
            if self._calls % self._PURGE_EVERY == 0:
                self._purge(cutoff)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(hits[0] - cutoff, 0.001)
            hits.append(now)
            return 0.0

    def _purge(self, cutoff: float) -> None:
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


def retry_after_header(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


class RenderSlots:
    """Bounded number of simultaneous PDF renders; waits up to ``timeout`` seconds for a slot."""

    def __init__(self, size: int, timeout: float) -> None:
        self._semaphore = threading.BoundedSemaphore(size)
        self.timeout = timeout

    @contextmanager
    def acquire(self) -> Iterator[None]:
        if not self._semaphore.acquire(timeout=self.timeout):
            raise HTTPException(status_code=503, detail=MSG_BUSY, headers=retry_after_header(5))
        try:
            yield
        finally:
            self._semaphore.release()
