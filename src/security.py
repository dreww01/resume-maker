import time
import threading
from typing import Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

# Maximum request body size allowed (5MB)
MAX_REQUEST_BODY_SIZE = 5 * 1024 * 1024


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces a maximum payload size limit on incoming requests.
    Rejects requests exceeding the size limit with HTTP 413 Payload Too Large.
    """

    def __init__(self, app, max_content_size: int = MAX_REQUEST_BODY_SIZE):
        super().__init__(app)
        self.max_content_size = max_content_size

    async def dispatch(self, request: Request, call_next):
        status_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_content_size:
                    return JSONResponse(
                        status_code=status_413,
                        content={"detail": "Payload Too Large"}
                    )
            except (ValueError, TypeError):
                pass

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that attaches standard security response headers to all outgoing responses.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class TokenBucket:
    """Internal state for a single token bucket."""
    __slots__ = ("tokens", "last_updated")

    def __init__(self, tokens: float, last_updated: float):
        self.tokens = tokens
        self.last_updated = last_updated


class TokenBucketRateLimiter:
    """
    In-memory Token Bucket rate limiter per client IP with automatic idle entry eviction.

    - Default: 60 requests per 60 seconds (1 token/sec refill rate).
    - Evicts entries idle for longer than `idle_timeout` to prevent unbounded memory growth.
    """

    def __init__(
        self,
        rate: int = 60,
        per: float = 60.0,
        idle_timeout: float = 60.0,
        cleanup_interval: float = 60.0,
    ):
        self.rate = float(rate)
        self.per = float(per)
        self.refill_rate = self.rate / self.per
        self.idle_timeout = float(idle_timeout)
        self.cleanup_interval = float(cleanup_interval)
        self.last_cleanup: Optional[float] = None
        self.buckets: dict[str, TokenBucket] = {}
        self.lock = threading.Lock()

    def _get_client_ip(self, request: Request) -> str:
        """Extracts the client IP address from request headers or socket address."""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        if request.client and request.client.host:
            return request.client.host
        return "127.0.0.1"

    def evict_idle(self, idle_timeout: Optional[float] = None, now: Optional[float] = None) -> int:
        """
        Evicts client IP entries that have been idle for longer than `idle_timeout`.
        Returns the number of entries removed.
        """
        if now is None:
            now = time.time()
        timeout = self.idle_timeout if idle_timeout is None else float(idle_timeout)
        evicted = 0
        with self.lock:
            idle_keys = [
                ip for ip, bucket in self.buckets.items()
                if (now - bucket.last_updated) >= timeout
            ]
            for ip in idle_keys:
                del self.buckets[ip]
                evicted += 1
            self.last_cleanup = now
        return evicted

    def is_allowed(self, client_ip: str, now: Optional[float] = None) -> bool:
        """
        Evaluates token availability for the given client IP. Deducts 1 token if allowed.
        """
        if now is None:
            now = time.time()

        with self.lock:
            if self.last_cleanup is None:
                self.last_cleanup = now
            elif (now - self.last_cleanup) >= self.cleanup_interval:
                idle_keys = [
                    ip for ip, bucket in self.buckets.items()
                    if (now - bucket.last_updated) >= self.idle_timeout
                ]
                for ip in idle_keys:
                    del self.buckets[ip]
                self.last_cleanup = now

            bucket = self.buckets.get(client_ip)
            if bucket is None:
                # First request from this client IP
                self.buckets[client_ip] = TokenBucket(tokens=self.rate - 1.0, last_updated=now)
                return True

            # Refill tokens proportional to elapsed time
            elapsed = max(0.0, now - bucket.last_updated)
            bucket.tokens = min(self.rate, bucket.tokens + elapsed * self.refill_rate)
            bucket.last_updated = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def reset(self):
        """Clears all stored bucket states."""
        with self.lock:
            self.buckets.clear()
            self.last_cleanup = None

    async def __call__(self, request: Request):
        """FastAPI dependency callable."""
        client_ip = self._get_client_ip(request)
        if not self.is_allowed(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too Many Requests"
            )


# Default shared rate limiter instance (60 requests/minute)
rate_limiter = TokenBucketRateLimiter(rate=60, per=60.0)
