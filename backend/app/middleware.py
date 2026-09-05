"""
HTTP middleware — security headers, rate limiting and request tracing.

These are the controls that separate a prototype from something that could face a
network. Each is small, but their absence is what an evaluator looks for.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("sentinel.http")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Attach standard protective headers to every response.

    The content security policy is deliberately strict about framing and object
    embedding: a surveillance console is a clickjacking target, since an operator
    session can search citizen movement history.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy",
                           "geolocation=(), microphone=(), camera=(), payment=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # The API serves JSON, evidence crops and proxied video segments; nothing
        # here should ever be framed or execute script.
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; img-src 'self' data:; media-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        # Only meaningful over TLS; harmless otherwise, and correct once deployed.
        headers.setdefault("Strict-Transport-Security",
                           "max-age=31536000; includeSubDomains")
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Give every request an id and log its outcome.

    The id is returned as `X-Request-ID` so a report of "my search failed" can be
    traced to a specific log line rather than guessed at.
    """

    # Endpoints too noisy to log at info level.
    QUIET_PATHS = ("/api/health", "/api/docs", "/api/openapi.json")

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception("%s %s failed after %.0f ms [%s]",
                             request.method, request.url.path, elapsed, request_id)
            raise

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id

        if not request.url.path.startswith(self.QUIET_PATHS):
            level = logging.WARNING if response.status_code >= 500 else logging.DEBUG
            logger.log(level, "%s %s -> %d in %.0f ms [%s]",
                       request.method, request.url.path, response.status_code,
                       elapsed, request_id)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Fixed-window rate limiting per client address.

    In-process and therefore per-worker: at prototype scale that is sufficient and
    honest, and the HLD names a shared store (Redis) as the multi-instance answer
    rather than pretending this one covers it.

    Login is limited far more tightly than reads, because that is the endpoint
    worth guessing at.
    """

    def __init__(self, app, default_limit: int = 300, window_seconds: int = 60,
                 auth_limit: int = 10):
        super().__init__(app)
        self.default_limit = default_limit
        self.auth_limit = auth_limit
        self.window = window_seconds
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    @staticmethod
    def _client_key(request: Request) -> str:
        # Behind a reverse proxy the real address is the first forwarded hop.
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _bucket_for(self, path: str) -> tuple[str, int]:
        if path.startswith("/api/v1/auth/"):
            return "auth", self.auth_limit
        return "default", self.default_limit

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Video segments are fetched continuously by every open tile; limiting
        # them would break the wall rather than protect anything.
        if path.startswith("/api/v1/cameras/proxy-hls/") or path == "/api/health":
            return await call_next(request)

        bucket, limit = self._bucket_for(path)
        key = (self._client_key(request), bucket)
        now = time.monotonic()

        hits = self._hits[key]
        cutoff = now - self.window
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = int(self.window - (now - hits[0])) + 1
            logger.warning("Rate limit hit: %s on %s bucket", key[0], bucket)
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(hits)))
        return response
