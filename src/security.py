import time
import threading
from typing import Dict, Tuple
from fastapi import Request, HTTPException, status
from starlette.responses import JSONResponse

MAX_REQUEST_BODY_SIZE = 5 * 1024 * 1024  # 5 MB


class ContentSizeLimitMiddleware:
    """
    ASGI middleware rejecting incoming request payloads exceeding max_size (5MB)
    with HTTP 413 Payload Too Large.
    Checks Content-Length upfront and tracks streaming request bodies.
    """
    def __init__(self, app, max_upload_size: int = MAX_REQUEST_BODY_SIZE):
        self.app = app
        self.max_upload_size = max_upload_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length.decode("latin1")) > self.max_upload_size:
                    response = JSONResponse(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content={"detail": f"Payload Too Large. Maximum allowed size is {self.max_upload_size} bytes (5MB)."}
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        total_received = 0

        async def limited_receive():
            nonlocal total_received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                total_received += len(body)
                if total_received > self.max_upload_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"Payload Too Large. Maximum allowed size is {self.max_upload_size} bytes (5MB)."
                    )
            return message

        try:
            await self.app(scope, limited_receive, send)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_413_CONTENT_TOO_LARGE:
                response = JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": exc.detail}
                )
                await response(scope, receive, send)
            else:
                raise


class SecurityHeadersMiddleware:
    """
    ASGI middleware injecting industry-standard security headers into all responses:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Strict-Transport-Security: max-age=31536000; includeSubDomains
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class TokenBucketRateLimiter:
    """
    Thread-safe in-memory token-bucket rate limiter per client IP.
    Evicts idle IP entries to prevent unbounded memory growth.
    """
    def __init__(self, rate: float = 60.0, per_seconds: float = 60.0, idle_timeout: float = 300.0):
        self.rate = float(rate)  # Maximum bucket capacity
        self.per_seconds = float(per_seconds)
        self.idle_timeout = float(idle_timeout)  # Eviction threshold in seconds
        # map: ip -> (tokens: float, last_update_time: float)
        self.buckets: Dict[str, Tuple[float, float]] = {}
        self.lock = threading.Lock()

    def _cleanup_idle_entries(self, current_time: float):
        """Removes IP entries that have been idle longer than idle_timeout."""
        stale_ips = [
            ip for ip, (_, last_update) in self.buckets.items()
            if current_time - last_update > self.idle_timeout
        ]
        for ip in stale_ips:
            del self.buckets[ip]

    def is_allowed(self, client_ip: str) -> bool:
        current_time = time.monotonic()
        with self.lock:
            self._cleanup_idle_entries(current_time)

            if client_ip not in self.buckets:
                # First request from this IP: full capacity minus 1
                self.buckets[client_ip] = (self.rate - 1.0, current_time)
                return True

            tokens, last_update = self.buckets[client_ip]
            elapsed = current_time - last_update
            # Replenish tokens proportional to elapsed time
            tokens = min(self.rate, tokens + elapsed * (self.rate / self.per_seconds))

            if tokens >= 1.0:
                self.buckets[client_ip] = (tokens - 1.0, current_time)
                return True
            else:
                self.buckets[client_ip] = (tokens, current_time)
                return False

    def reset(self):
        """Reset all rate limiter state (useful for tests)."""
        with self.lock:
            self.buckets.clear()


# Default instance: 60 requests per 60 seconds (1 minute) per client IP
rate_limiter = TokenBucketRateLimiter(rate=60.0, per_seconds=60.0, idle_timeout=300.0)


async def rate_limit_dependency(request: Request):
    """FastAPI route dependency to enforce rate limiting."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 60 requests per minute allowed."
        )
