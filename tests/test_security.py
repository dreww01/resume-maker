import os
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient

LINEAR_WEBHOOK_SECRET = "test-linear-secret"
GITHUB_WEBHOOK_SECRET = "test-github-secret"
os.environ["LINEAR_WEBHOOK_SECRET"] = LINEAR_WEBHOOK_SECRET
os.environ["GITHUB_WEBHOOK_SECRET"] = GITHUB_WEBHOOK_SECRET

from src.api import app
from src.security import (
    rate_limiter,
    verify_linear_hmac,
    verify_github_hmac,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


client = TestClient(app)


def test_payload_too_large_content_length():
    """Requests with Content-Length > 5MB return 413."""
    over_limit = 5 * 1024 * 1024 + 1
    response = client.post(
        "/",
        content=b"x",
        headers={"Content-Length": str(over_limit)}
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Payload Too Large"


def test_payload_too_large_actual_body():
    """Requests with actual body > 5MB return 413."""
    body = b"x" * (5 * 1024 * 1024 + 10)
    response = client.post(
        "/api/thinking",
        content=body,
        headers={"Content-Type": "application/octet-stream"}
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Payload Too Large"


def test_payload_within_limit():
    """Requests within 5MB limit succeed or pass payload size validation."""
    response = client.get("/")
    assert response.status_code == 200


def test_rate_limiting_burst():
    """Bursting 65 requests returns 429 after 60 requests."""
    endpoints = ["/webhook/linear", "/webhook/github", "/api/thinking"]
    for endpoint in endpoints:
        rate_limiter.reset()
        for i in range(60):
            res = client.get(endpoint) if endpoint == "/api/thinking" else client.post(endpoint, content=b"")
            assert res.status_code != 429, f"Request {i+1} failed on {endpoint} with {res.status_code}"

        # 61st to 65th request should be rate limited (429)
        for i in range(60, 65):
            res = client.get(endpoint) if endpoint == "/api/thinking" else client.post(endpoint, content=b"")
            assert res.status_code == 429, f"Request {i+1} did not return 429 on {endpoint}, got {res.status_code}"
            assert res.json()["detail"] == "Too Many Requests"


def test_rate_limiting_x_forwarded_for_spoofing():
    """Spoofed X-Forwarded-For header does not bypass rate limiter."""
    rate_limiter.reset()
    for i in range(60):
        res = client.get("/api/thinking", headers={"X-Forwarded-For": f"1.1.1.{i}"})
        assert res.status_code == 200

    # 61st request with a new spoofed IP is still rate limited by direct client IP
    res = client.get("/api/thinking", headers={"X-Forwarded-For": "9.9.9.9"})
    assert res.status_code == 429


def test_hmac_valid_and_invalid_linear():
    """Valid and invalid HMAC signatures for Linear webhook."""
    payload = b'{"action": "issue.create"}'
    valid_sig = hmac.new(LINEAR_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    # Valid signature
    res = client.post(
        "/webhook/linear",
        content=payload,
        headers={"Linear-Signature": valid_sig, "Content-Type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # Invalid signature
    res = client.post(
        "/webhook/linear",
        content=payload,
        headers={"Linear-Signature": "invalid_signature", "Content-Type": "application/json"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid signature"

    # Missing signature
    res = client.post(
        "/webhook/linear",
        content=payload,
        headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 401


def test_hmac_valid_and_invalid_github():
    """Valid and invalid HMAC signatures for GitHub webhook."""
    payload = b'{"ref": "refs/heads/master"}'
    valid_hex = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    valid_sig = f"sha256={valid_hex}"

    # Valid signature
    res = client.post(
        "/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # Invalid signature
    res = client.post(
        "/webhook/github",
        content=payload,
        headers={"X-Hub-Signature-256": "sha256=invalid", "Content-Type": "application/json"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid signature"

    # Missing signature
    res = client.post(
        "/webhook/github",
        content=payload,
        headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 401


def test_hmac_timing_safe_function():
    """Test verify_linear_hmac and verify_github_hmac edge cases directly."""
    payload = b"test payload"
    # None signature
    assert not verify_linear_hmac(None, payload)
    assert not verify_github_hmac(None, payload)
    # Empty signature
    assert not verify_linear_hmac("", payload)
    assert not verify_github_hmac("", payload)
    # Wrong format
    assert not verify_linear_hmac("123", payload)
    assert not verify_github_hmac("123", payload)
    # Missing secret with env unset
    old_linear = os.environ.pop("LINEAR_WEBHOOK_SECRET", None)
    old_github = os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
    try:
        assert not verify_linear_hmac("some_sig", payload)
        assert not verify_github_hmac("sha256=some_sig", payload)
    finally:
        if old_linear:
            os.environ["LINEAR_WEBHOOK_SECRET"] = old_linear
        if old_github:
            os.environ["GITHUB_WEBHOOK_SECRET"] = old_github


def test_token_bucket_max_keys_eviction():
    """TokenBucketRateLimiter evicts stale keys or clears when reaching max_keys."""
    from src.security import TokenBucketRateLimiter
    limiter = TokenBucketRateLimiter(rate=60.0, capacity=60.0, per_seconds=60.0, max_keys=3)
    assert limiter.is_allowed("1.1.1.1")
    assert limiter.is_allowed("1.1.1.2")
    assert limiter.is_allowed("1.1.1.3")
    assert len(limiter.buckets) == 3
    # Adding a 4th key when none are stale clears/evicts to bound memory
    assert limiter.is_allowed("1.1.1.4")
    assert len(limiter.buckets) <= 3


def test_security_headers_present():
    """All API responses include required security headers."""
    endpoints = ["/", "/api/thinking"]
    for ep in endpoints:
        res = client.get(ep)
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("X-Frame-Options") == "DENY"
        assert res.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"

    # Also test error response has security headers
    res = client.post("/", content=b"x", headers={"Content-Length": str(10 * 1024 * 1024)})
    assert res.status_code == 413
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_cors_headers_on_413():
    """CORS headers are attached to 413 responses from RequestSizeLimitMiddleware."""
    res = client.post(
        "/",
        content=b"x",
        headers={
            "Content-Length": str(10 * 1024 * 1024),
            "Origin": "http://example.com"
        }
    )
    assert res.status_code == 413
    assert res.headers.get("access-control-allow-origin") == "*"
