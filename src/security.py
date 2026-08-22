import os
import time
import hmac
import hashlib
from typing import Dict, Tuple
from fastapi import Request, HTTPException, status, Header, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send, Message

MAX_REQUEST_BODY_SIZE = 5 * 1024 * 1024  # 5 MB


class RequestSizeLimitMiddleware:
    """
    Pure ASGI middleware to enforce request body size limit of 5MB.
    Rejects with HTTP 413 Payload Too Large if Content-Length header or streamed body exceeds max_size.
    """
    def __init__(self, app: ASGIApp, max_size: int = MAX_REQUEST_BODY_SIZE):
        self.app = app
        self.max_size = max_size

    def _create_413_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={"detail": "Payload Too Large"},
            headers={
                "Access-Control-Allow-Origin": "*",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
            }
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check Content-Length header first
        content_length_header = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                content_length_header = value
                break

        if content_length_header:
            try:
                if int(content_length_header) > self.max_size:
                    response = self._create_413_response()
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        received_bytes = 0

        async def custom_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > self.max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="Payload Too Large"
                    )
            return message

        try:
            await self.app(scope, custom_receive, send)
        except HTTPException as exc:
            if exc.status_code == 413:
                response = self._create_413_response()
                await response(scope, receive, send)
            else:
                raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class TokenBucketRateLimiter:
    def __init__(self, rate: float = 60.0, capacity: float = 60.0, per_seconds: float = 60.0, max_keys: int = 10000):
        self.rate = rate / per_seconds  # tokens per second
        self.capacity = capacity
        self.max_keys = max_keys
        # Mapping from ip -> (tokens, last_time)
        self.buckets: Dict[str, Tuple[float, float]] = {}

    def is_allowed(self, client_ip: str) -> bool:
        now = time.monotonic()
        if client_ip not in self.buckets:
            if len(self.buckets) >= self.max_keys:
                # Evict stale buckets that have fully regenerated
                idle_threshold = self.capacity / self.rate
                stale_keys = [ip for ip, (_, last_time) in self.buckets.items() if now - last_time > idle_threshold]
                for ip in stale_keys:
                    self.buckets.pop(ip, None)
                if len(self.buckets) >= self.max_keys:
                    self.buckets.clear()
            self.buckets[client_ip] = (self.capacity - 1.0, now)
            return True

        tokens, last_time = self.buckets[client_ip]
        elapsed = now - last_time
        tokens = min(self.capacity, tokens + elapsed * self.rate)

        if tokens >= 1.0:
            self.buckets[client_ip] = (tokens - 1.0, now)
            return True
        else:
            self.buckets[client_ip] = (tokens, now)
            return False

    def reset(self):
        self.buckets.clear()


# Rate limiter allowing max 60 requests/minute per client IP
rate_limiter = TokenBucketRateLimiter(rate=60.0, capacity=60.0, per_seconds=60.0)


def rate_limit_dependency(request: Request):
    # Only trust X-Forwarded-For if behind a verified trusted reverse proxy; otherwise rely on direct client host
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too Many Requests"
        )


def verify_linear_hmac(signature: str | None, payload: bytes, secret: str | None = None) -> bool:
    """
    Validates Linear-Signature header using constant-time comparison (HMAC-SHA256).
    Defensive against missing or malformed headers and missing secret.
    """
    webhook_secret = secret or os.getenv("LINEAR_WEBHOOK_SECRET")
    if not webhook_secret:
        return False
    expected_sig = hmac.new(webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not signature or not isinstance(signature, str):
        return False
    return hmac.compare_digest(expected_sig, signature.strip())


def verify_github_hmac(signature: str | None, payload: bytes, secret: str | None = None) -> bool:
    """
    Validates X-Hub-Signature-256 header using constant-time comparison (HMAC-SHA256 with sha256= prefix).
    Defensive against missing or malformed headers and missing secret.
    """
    webhook_secret = secret or os.getenv("GITHUB_WEBHOOK_SECRET")
    if not webhook_secret:
        return False
    expected_hex = hmac.new(webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    expected_sig = f"sha256={expected_hex}"
    if not signature or not isinstance(signature, str):
        return False
    return hmac.compare_digest(expected_sig, signature.strip())
