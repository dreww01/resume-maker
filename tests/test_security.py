import io
import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure OPENAI_API_KEY is set before importing src.api
os.environ.setdefault("OPENAI_API_KEY", "test_openai_api_key")

from src.api import app
from src.security import (
    RateLimiter,
    RequestBodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    TokenBucket,
    get_client_ip,
    rate_limiter,
)


@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset the global rate limiter before each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Security Response Headers Tests
# ---------------------------------------------------------------------------


def test_security_headers_on_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert (
        response.headers.get("strict-transport-security")
        == "max-age=31536000; includeSubDomains"
    )


def test_security_headers_on_404_not_found(client):
    response = client.get("/nonexistent-endpoint")
    assert response.status_code == 404
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert (
        response.headers.get("strict-transport-security")
        == "max-age=31536000; includeSubDomains"
    )


def test_security_headers_on_400_bad_request(client):
    # Invalid file extension
    files = {"file": ("test.txt", b"plain text", "text/plain")}
    response = client.post("/upload", files=files)
    assert response.status_code == 400
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert (
        response.headers.get("strict-transport-security")
        == "max-age=31536000; includeSubDomains"
    )


def test_security_headers_on_413_payload_too_large(client):
    # Send Content-Length > 5MB
    large_size = 5 * 1024 * 1024 + 1
    response = client.post(
        "/upload",
        headers={"Content-Length": str(large_size)},
        content=b"x",
    )
    assert response.status_code == 413
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert (
        response.headers.get("strict-transport-security")
        == "max-age=31536000; includeSubDomains"
    )


def test_security_headers_on_429_rate_limit(client):
    # Exhaust rate limit
    for _ in range(60):
        client.post("/upload", files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")})
    response = client.post(
        "/upload", files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert response.status_code == 429
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert (
        response.headers.get("strict-transport-security")
        == "max-age=31536000; includeSubDomains"
    )


# ---------------------------------------------------------------------------
# 2. Request Body Size Limit Middleware Tests
# ---------------------------------------------------------------------------


def test_request_body_size_limit_header_exceeded(client):
    max_limit = 5 * 1024 * 1024  # 5MB
    exceeded_size = max_limit + 1024

    response = client.post(
        "/upload",
        headers={"Content-Length": str(exceeded_size)},
        content=b"test",
    )
    assert response.status_code == 413
    assert "Payload Too Large" in response.text


def test_request_body_size_limit_exact_5mb_accepted(client):
    max_limit = 5 * 1024 * 1024  # 5MB
    # Header indicates 5MB exactly
    response = client.post(
        "/upload",
        headers={"Content-Length": str(max_limit)},
        files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
    )
    # Status should not be 413 (it might be 200 or 400 depending on payload parsing)
    assert response.status_code != 413


def test_request_body_size_limit_on_tailor_endpoint(client):
    max_limit = 5 * 1024 * 1024
    exceeded_size = max_limit + 100
    response = client.post(
        "/resumes/1/tailor",
        headers={"Content-Length": str(exceeded_size), "Content-Type": "text/plain"},
        content="job description",
    )
    assert response.status_code == 413


def test_request_body_size_limit_large_file_upload(client):
    large_file = b"%PDF-1.4\n" + b"0" * (6 * 1024 * 1024)
    response = client.post(
        "/upload",
        files={"file": ("large.pdf", large_file, "application/pdf")},
    )
    assert response.status_code == 413
    assert "Payload Too Large" in response.text


def test_request_body_size_limit_streaming_exceeded(client):
    def large_stream():
        chunk = b"a" * (1024 * 1024)
        for _ in range(6):  # 6MB total
            yield chunk

    response = client.post(
        "/resumes/1/tailor",
        content=large_stream(),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# 3. Token-Bucket Rate Limiter Tests
# ---------------------------------------------------------------------------


def test_rate_limiter_burst_upload_endpoint(client):
    # Send 60 allowed requests
    for i in range(60):
        res = client.post(
            "/upload",
            files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"X-Forwarded-For": "192.168.1.100"},
        )
        assert res.status_code == 200, f"Request {i+1} failed with {res.status_code}"

    # Requests 61 to 65 must return 429
    for i in range(61, 66):
        res = client.post(
            "/upload",
            files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"X-Forwarded-For": "192.168.1.100"},
        )
        assert res.status_code == 429, f"Request {i} did not return 429 (status={res.status_code})"
        assert "Retry-After" in res.headers


def test_rate_limiter_burst_tailor_endpoint(client):
    # Target endpoint /resumes/{resume_id}/tailor
    for i in range(60):
        res = client.post(
            "/resumes/999/tailor",
            content="Senior Software Engineer",
            headers={
                "Content-Type": "text/plain",
                "X-Forwarded-For": "192.168.1.101",
            },
        )
        # Should reach route logic (404 Resume not found) but pass rate limiter
        assert res.status_code == 404, f"Request {i+1} got unexpected status {res.status_code}"

    # 61st to 65th requests return 429
    for i in range(61, 66):
        res = client.post(
            "/resumes/999/tailor",
            content="Senior Software Engineer",
            headers={
                "Content-Type": "text/plain",
                "X-Forwarded-For": "192.168.1.101",
            },
        )
        assert res.status_code == 429, f"Request {i} did not return 429 (status={res.status_code})"


def test_rate_limiter_burst_cover_letter_endpoint(client):
    # Target endpoint /resumes/{resume_id}/cover-letter
    for i in range(60):
        res = client.post(
            "/resumes/999/cover-letter",
            content="Senior Software Engineer",
            headers={
                "Content-Type": "text/plain",
                "X-Forwarded-For": "192.168.1.102",
            },
        )
        assert res.status_code == 404, f"Request {i+1} got unexpected status {res.status_code}"

    # 61st onwards returns 429
    res = client.post(
        "/resumes/999/cover-letter",
        content="Senior Software Engineer",
        headers={
            "Content-Type": "text/plain",
            "X-Forwarded-For": "192.168.1.102",
        },
    )
    assert res.status_code == 429


def test_rate_limiter_isolated_by_ip(client):
    # Client 1 exhausts 60 requests
    for _ in range(60):
        res = client.post(
            "/upload",
            files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert res.status_code == 200

    # Client 1 is now rate limited
    res1 = client.post(
        "/upload",
        files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
        headers={"X-Forwarded-For": "10.0.0.1"},
    )
    assert res1.status_code == 429

    # Client 2 should still be allowed
    res2 = client.post(
        "/upload",
        files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert res2.status_code == 200


def test_rate_limiter_refills_tokens():
    limiter = RateLimiter(rate=2, per=1.0)
    bucket = TokenBucket(capacity=2.0, refill_rate=2.0)

    # Consume 2 tokens
    assert bucket.consume(1.0, now=100.0) is True
    assert bucket.consume(1.0, now=100.0) is True
    # Out of tokens
    assert bucket.consume(1.0, now=100.0) is False

    # After 0.5s, 1 token is refilled (0.5 * 2 = 1)
    assert bucket.consume(1.0, now=100.5) is True
    assert bucket.consume(1.0, now=100.5) is False

    # After 1.0s more, 2 tokens refilled (capped at capacity 2)
    assert bucket.consume(1.0, now=101.5) is True
    assert bucket.consume(1.0, now=101.5) is True
    assert bucket.consume(1.0, now=101.5) is False


def test_rate_limiter_idle_ip_eviction():
    limiter = RateLimiter(rate=60, per=60.0, idle_timeout=60.0)

    # Populate several IPs at t=100.0
    now = 100.0
    for i in range(5):
        ip = f"192.168.1.{i}"
        limiter._buckets[ip] = TokenBucket(capacity=60.0, refill_rate=1.0)
        limiter._buckets[ip].last_updated = now

    assert limiter.get_bucket_count() == 5

    # At t=130.0 (idle 30s < 60s timeout), no eviction
    with patch("time.monotonic", return_value=130.0):
        evicted = limiter.cleanup_idle()
        assert evicted == 0
        assert limiter.get_bucket_count() == 5

    # Update IP 0 activity at t=150.0
    limiter._buckets["192.168.1.0"].last_updated = 150.0

    # At t=170.0 (idle 70s for IPs 1-4, 20s for IP 0)
    with patch("time.monotonic", return_value=170.0):
        evicted = limiter.cleanup_idle()
        assert evicted == 4
        assert limiter.get_bucket_count() == 1
        assert "192.168.1.0" in limiter._buckets
