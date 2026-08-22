import math
import threading
import time
from typing import Optional

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request headers or client socket."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return client_ip
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


class TokenBucket:
    """Thread-safe Token Bucket for rate limiting."""

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last_updated = time.monotonic()

    def consume(self, tokens: float = 1.0, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.monotonic()
        elapsed = max(0.0, now - self.last_updated)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_updated = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class RateLimiter:
    """In-memory Token-Bucket rate limiter with idle IP entry eviction."""

    def __init__(
        self,
        rate: int = 60,
        per: float = 60.0,
        idle_timeout: float = 60.0,
        cleanup_interval: float = 60.0,
    ):
        self.rate = rate
        self.per = per
        self.idle_timeout = idle_timeout
        self.cleanup_interval = cleanup_interval
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def _cleanup_idle_locked(self, now: float, max_idle_seconds: float) -> int:
        to_delete = [
            ip
            for ip, bucket in self._buckets.items()
            if (now - bucket.last_updated) > max_idle_seconds
        ]
        for ip in to_delete:
            del self._buckets[ip]
        return len(to_delete)

    def cleanup_idle(self, max_idle_seconds: Optional[float] = None) -> int:
        """Evict IP entries that have been idle longer than max_idle_seconds."""
        if max_idle_seconds is None:
            max_idle_seconds = self.idle_timeout
        now = time.monotonic()
        with self._lock:
            return self._cleanup_idle_locked(now, max_idle_seconds)

    def reset(self):
        """Reset all rate limiter state."""
        with self._lock:
            self._buckets.clear()
            self._last_cleanup = time.monotonic()

    def get_bucket_count(self) -> int:
        """Return the current number of tracked IP entries."""
        with self._lock:
            return len(self._buckets)

    def check(self, request: Request):
        client_ip = get_client_ip(request)
        now = time.monotonic()

        with self._lock:
            if (now - self._last_cleanup) >= self.cleanup_interval:
                self._cleanup_idle_locked(now, self.idle_timeout)
                self._last_cleanup = now

            bucket = self._buckets.get(client_ip)
            if bucket is None:
                bucket = TokenBucket(
                    capacity=float(self.rate),
                    refill_rate=float(self.rate) / self.per,
                )
                self._buckets[client_ip] = bucket

            allowed = bucket.consume(1.0, now=now)
            if not allowed:
                needed = 1.0 - bucket.tokens
                retry_after = max(1, int(math.ceil(needed / bucket.refill_rate)))
                raise HTTPException(
                    status_code=429,
                    detail="Too Many Requests",
                    headers={"Retry-After": str(retry_after)},
                )

    async def __call__(self, request: Request):
        self.check(request)


# Default rate limiter: 60 requests per 60 seconds (1 min)
rate_limiter = RateLimiter(rate=60, per=60.0)


class RequestBodySizeLimitMiddleware:
    """Middleware rejecting incoming request payloads exceeding max_body_size (default 5MB)
    with HTTP 413 Payload Too Large.
    """

    def __init__(self, app: ASGIApp, max_body_size: int = 5 * 1024 * 1024):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check Content-Length header if present
        content_length_val = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    content_length_val = int(value.decode("latin-1"))
                except ValueError:
                    pass
                break

        if content_length_val is not None and content_length_val > self.max_body_size:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Payload Too Large"},
            )
            await response(scope, receive, send)
            return

        # Check stream/chunk size during receive
        received_bytes = 0

        async def custom_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > self.max_body_size:
                    raise HTTPException(
                        status_code=413,
                        detail="Payload Too Large",
                    )
            return message

        await self.app(scope, custom_receive, send)


class SecurityHeadersMiddleware:
    """Middleware injecting security response headers:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Strict-Transport-Security: max-age=31536000; includeSubDomains
    """

    SECURITY_HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    ]

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                sec_keys = {k for k, _ in self.SECURITY_HEADERS}
                filtered_headers = [
                    (k, v) for k, v in headers if k.lower() not in sec_keys
                ]
                filtered_headers.extend(self.SECURITY_HEADERS)
                message["headers"] = filtered_headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
