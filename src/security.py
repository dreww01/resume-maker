"""
Security utilities and middleware for FastAPI:
1. Content-Length / Request Body Size Limit Middleware (reject > 5MB with 413)
2. In-memory Token-Bucket Rate Limiter with idle IP eviction (max 60 req/min per IP, reject with 429)
3. Security Response Headers Middleware (X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security)
"""

import time
import threading
from typing import Callable, Dict, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.types import ASGIApp
from fastapi import Request as FastAPIRequest, HTTPException, status


# 5MB in bytes: 5 * 1024 * 1024 = 5,242,880 bytes
DEFAULT_MAX_BODY_SIZE = 5 * 1024 * 1024


HTTP_413_PAYLOAD_TOO_LARGE = 413
HTTP_429_TOO_MANY_REQUESTS = 429


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that rejects incoming requests with bodies exceeding max_bytes.
    Checks Content-Length header first, and dynamically counts streaming bytes.
    Returns HTTP 413 Payload Too Large if exceeded.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_SIZE):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
                if length > self.max_bytes:
                    return JSONResponse(
                        status_code=HTTP_413_PAYLOAD_TOO_LARGE,
                        content={"detail": "Payload too large. Maximum allowed size is 5MB."},
                    )
            except ValueError:
                pass

        # Handle chunked / streaming transfers without Content-Length or within threshold
        received_bytes = 0
        original_receive = request._receive

        async def receive_with_limit():
            nonlocal received_bytes
            message = await original_receive()
            if message.get("type") == "http.request":
                body_chunk = message.get("body", b"")
                received_bytes += len(body_chunk)
                if received_bytes > self.max_bytes:
                    raise HTTPException(
                        status_code=HTTP_413_PAYLOAD_TOO_LARGE,
                        detail="Payload too large. Maximum allowed size is 5MB.",
                    )
            return message

        request._receive = receive_with_limit

        try:
            return await call_next(request)
        except HTTPException as exc:
            if exc.status_code == HTTP_413_PAYLOAD_TOO_LARGE:
                return JSONResponse(
                    status_code=HTTP_413_PAYLOAD_TOO_LARGE,
                    content={"detail": exc.detail},
                )
            raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that injects standard security response headers:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Strict-Transport-Security: max-age=31536000; includeSubDomains
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class TokenBucketRateLimiter:
    """
    Thread-safe in-memory Token Bucket rate limiter with idle IP eviction.
    - rate: tokens added per second
    - capacity: maximum burst capacity
    - max_idle_time: seconds of inactivity before an IP entry is evicted
    """

    def __init__(self, rate_per_minute: int = 60, capacity: Optional[int] = None, max_idle_time: float = 300.0):
        self.rate = rate_per_minute / 60.0  # tokens per second
        self.capacity = float(capacity if capacity is not None else rate_per_minute)
        self.max_idle_time = max_idle_time
        self.lock = threading.Lock()
        # Storage: ip -> [current_tokens, last_refill_timestamp, last_active_timestamp]
        self.buckets: Dict[str, list] = {}
        self.last_eviction = time.monotonic()

    def _evict_idle(self, now: float) -> None:
        """Evict IP entries that haven't been active for max_idle_time."""
        # Run eviction check if at least 60 seconds passed or map size is significant
        if now - self.last_eviction > 60.0 or len(self.buckets) > 1000:
            idle_keys = [
                ip for ip, data in self.buckets.items()
                if (now - data[2]) > self.max_idle_time
            ]
            for ip in idle_keys:
                del self.buckets[ip]
            self.last_eviction = now

    def acquire(self, client_ip: str, tokens: float = 1.0) -> bool:
        """
        Attempt to acquire tokens for a client IP.
        Returns True if allowed, False if rate limit exceeded.
        """
        now = time.monotonic()
        with self.lock:
            self._evict_idle(now)

            if client_ip not in self.buckets:
                # Start fresh with full capacity minus requested tokens
                if self.capacity >= tokens:
                    self.buckets[client_ip] = [self.capacity - tokens, now, now]
                    return True
                return False

            bucket = self.buckets[client_ip]
            current_tokens, last_refill, _ = bucket

            # Calculate refilled tokens
            elapsed = now - last_refill
            refilled = current_tokens + (elapsed * self.rate)
            current_tokens = min(self.capacity, refilled)

            if current_tokens >= tokens:
                current_tokens -= tokens
                self.buckets[client_ip] = [current_tokens, now, now]
                return True
            else:
                # Update refill time and tokens, mark activity
                self.buckets[client_ip] = [current_tokens, now, now]
                return False

    def clear(self) -> None:
        """Clear all stored buckets (useful for tests)."""
        with self.lock:
            self.buckets.clear()
            self.last_eviction = time.monotonic()

    def __call__(self, request: FastAPIRequest) -> None:
        """FastAPI dependency callable."""
        # Determine client IP (support Forwarded/X-Forwarded-For if behind proxy, fallback to request.client.host)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif request.client and request.client.host:
            client_ip = request.client.host
        else:
            client_ip = "unknown"

        if not self.acquire(client_ip):
            raise HTTPException(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Maximum 60 requests per minute allowed.",
            )
