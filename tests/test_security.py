import io
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Set OPENAI_API_KEY before importing app if not set
import os
if not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = "test-api-key"

from src.api import app, rate_limiter
from src.security import ContentSizeLimitMiddleware, SecurityHeadersMiddleware, TokenBucketRateLimiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the global rate limiter before each test."""
    rate_limiter.clear()
    yield
    rate_limiter.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Security Response Headers Middleware Tests
# ---------------------------------------------------------------------------

def test_security_headers_present_on_get(client):
    """Verify all responses contain required security headers."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_present_on_post(client):
    """Verify security headers are present on POST requests."""
    fake_file = io.BytesIO(b"%PDF-1.4 test content")
    response = client.post(
        "/upload",
        files={"file": ("resume.pdf", fake_file, "application/pdf")}
    )
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_present_on_error_responses(client):
    """Verify security headers are present even on 404/400 error responses."""
    response = client.get("/resumes/999999")
    assert response.status_code == 404
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


# ---------------------------------------------------------------------------
# 2. Request Body Size Limit Middleware Tests
# ---------------------------------------------------------------------------

def test_payload_under_limit_accepted(client):
    """Payloads within 5MB limit are accepted."""
    small_content = b"%PDF-1.4 " + b"A" * 1024  # ~1KB
    response = client.post(
        "/upload",
        files={"file": ("resume.pdf", io.BytesIO(small_content), "application/pdf")}
    )
    assert response.status_code == 200


def test_payload_exceeding_content_length_rejected(client):
    """Requests with Content-Length > 5MB return HTTP 413 Payload Too Large."""
    # 5MB + 10 bytes = 5,242,890 bytes
    oversized_len = 5 * 1024 * 1024 + 10
    response = client.post(
        "/upload",
        headers={"Content-Length": str(oversized_len), "Content-Type": "application/octet-stream"},
        content=b"test"
    )
    assert response.status_code == 413
    assert "Payload too large" in response.json().get("detail", "")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_streaming_payload_exceeding_limit_rejected(client):
    """Streaming requests with actual body exceeding 5MB return HTTP 413."""
    limit = 5 * 1024 * 1024
    oversized_data = b"x" * (limit + 500)
    response = client.post(
        "/upload",
        files={"file": ("resume.pdf", io.BytesIO(oversized_data), "application/pdf")}
    )
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# 3. Rate Limiter Tests
# ---------------------------------------------------------------------------

def test_rate_limiter_allows_up_to_capacity(client):
    """Rate limiter allows 60 requests and blocks the 61st."""
    # Create a resume first so tailor endpoint has a target
    upload_resp = client.post(
        "/upload",
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    )
    assert upload_resp.status_code == 200
    resume_id = upload_resp.json()["id"]

    # 1 request was already consumed on /upload for client IP 'testclient'
    # Send remaining 59 requests to reach 60 total
    with patch("src.api.read_resume", return_value="dummy resume text"), \
         patch("src.api.call_openai", return_value={"name": "Jane", "work_experience": []}), \
         patch("src.api.create_docx", return_value=b"fake-docx"):
        for i in range(59):
            resp = client.post(
                f"/resumes/{resume_id}/tailor",
                content="Software Engineer job description",
                headers={"Content-Type": "text/plain"}
            )
            assert resp.status_code == 200, f"Request {i + 2} failed with status {resp.status_code}"

        # 61st request should be rate limited (429)
        blocked_resp = client.post(
            f"/resumes/{resume_id}/tailor",
            content="Software Engineer job description",
            headers={"Content-Type": "text/plain"}
        )
        assert blocked_resp.status_code == 429
        assert "Rate limit exceeded" in blocked_resp.json().get("detail", "")


def test_bursting_65_requests_returns_429_after_60(client):
    """Bursting 65 requests on /upload returns 429 after 60 requests."""
    fake_file = b"%PDF-1.4 test"
    success_count = 0
    blocked_count = 0

    for i in range(65):
        resp = client.post(
            "/upload",
            files={"file": ("resume.pdf", io.BytesIO(fake_file), "application/pdf")}
        )
        if resp.status_code == 200:
            success_count += 1
        elif resp.status_code == 429:
            blocked_count += 1

    assert success_count == 60
    assert blocked_count == 5


def test_rate_limiter_cover_letter_endpoint(client):
    """Verify rate limiter applies to /resumes/{resume_id}/cover-letter endpoint."""
    upload_resp = client.post(
        "/upload",
        files={"file": ("test.docx", io.BytesIO(b"PK\x03\x04test"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert upload_resp.status_code == 200
    resume_id = upload_resp.json()["id"]

    with patch("src.api.read_resume", return_value="dummy resume text"), \
         patch("src.api.call_openai_cover_letter", return_value={"name": "Jane", "content": "Dear Hiring Manager..."}), \
         patch("src.api.create_cover_letter_docx", return_value=b"fake-docx"):
        for _ in range(59):
            resp = client.post(
                f"/resumes/{resume_id}/cover-letter",
                content="Job description",
                headers={"Content-Type": "text/plain"}
            )
            assert resp.status_code == 200

        # 61st request overall
        resp = client.post(
            f"/resumes/{resume_id}/cover-letter",
            content="Job description",
            headers={"Content-Type": "text/plain"}
        )
        assert resp.status_code == 429


def test_rate_limiter_different_ips(client):
    """Requests from different client IPs have separate rate limits."""
    # Consume 60 requests for IP 1.1.1.1
    for _ in range(60):
        resp = client.post(
            "/upload",
            headers={"X-Forwarded-For": "1.1.1.1"},
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
        )
        assert resp.status_code == 200

    # 61st request from 1.1.1.1 is blocked
    resp = client.post(
        "/upload",
        headers={"X-Forwarded-For": "1.1.1.1"},
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    )
    assert resp.status_code == 429

    # IP 2.2.2.2 is allowed
    resp2 = client.post(
        "/upload",
        headers={"X-Forwarded-For": "2.2.2.2"},
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    )
    assert resp2.status_code == 200


def test_rate_limiter_idle_eviction():
    """Verify idle IP entries are evicted to prevent memory exhaustion."""
    limiter = TokenBucketRateLimiter(rate_per_minute=60, max_idle_time=0.1)
    
    # Acquire for ip1 and ip2
    assert limiter.acquire("10.0.0.1") is True
    assert limiter.acquire("10.0.0.2") is True
    assert "10.0.0.1" in limiter.buckets
    assert "10.0.0.2" in limiter.buckets

    # Sleep past max_idle_time
    time.sleep(0.15)
    limiter.last_eviction = 0  # Force eviction interval trigger

    # Acquire for a new IP triggers eviction
    assert limiter.acquire("10.0.0.3") is True
    assert "10.0.0.1" not in limiter.buckets
    assert "10.0.0.2" not in limiter.buckets
    assert "10.0.0.3" in limiter.buckets
