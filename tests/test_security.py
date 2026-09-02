import io
import time
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api import app
from src.security import rate_limiter, TokenBucketRateLimiter



@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the global rate limiter before each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Payload / Request Body Size Limit Tests (HTTP 413)
# ---------------------------------------------------------------------------

def test_payload_exceeding_content_length_returns_413(client):
    """Requests with Content-Length > 5MB must return 413 and include security headers."""
    oversized_length = (5 * 1024 * 1024) + 1  # 5MB + 1 byte
    response = client.post(
        "/resumes/1/tailor",
        headers={"Content-Length": str(oversized_length), "Content-Type": "text/plain"},
        content=b"x" * 100,  # Header declared oversized
    )
    assert response.status_code == 413
    assert "payload too large" in response.json()["detail"].lower()
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_payload_exceeding_body_size_returns_413(client):
    """Requests with actual body payload > 5MB must return 413 and include security headers."""
    oversized_data = b"x" * (5 * 1024 * 1024 + 100)
    response = client.post(
        "/resumes/1/tailor",
        content=oversized_data,
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 413
    assert "payload too large" in response.json()["detail"].lower()
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_file_upload_exceeding_5mb_returns_413(client):
    """File uploads exceeding 5MB must return 413 and include security headers."""
    oversized_bytes = b"a" * (5 * 1024 * 1024 + 50)
    files = {"file": ("resume.pdf", io.BytesIO(oversized_bytes), "application/pdf")}
    response = client.post("/upload", files=files)
    assert response.status_code == 413
    assert "payload too large" in response.json()["detail"].lower()
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_payload_within_5mb_allowed(client):
    """Requests under 5MB are allowed through the middleware."""
    response = client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. Security Response Headers Tests
# ---------------------------------------------------------------------------

def test_security_headers_on_root_endpoint(client):
    """All responses must include standard security headers."""
    response = client.get("/")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_on_error_responses(client):
    """Even error responses (e.g. 404, 413, 429) must include security headers."""
    response = client.get("/resumes/999999")
    assert response.status_code == 404
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


# ---------------------------------------------------------------------------
# 3. Token-Bucket Rate Limiting Tests (HTTP 429)
# ---------------------------------------------------------------------------

def test_rate_limiter_burst_on_upload(client):
    """Bursting 65 requests on /upload returns 429 after 60 requests."""
    files = {"file": ("resume.pdf", b"%PDF-1.4 dummy content", "application/pdf")}

    for i in range(60):
        # Rewind file buffer
        files = {"file": ("resume.pdf", b"%PDF-1.4 dummy content", "application/pdf")}
        resp = client.post("/upload", files=files)
        assert resp.status_code == 200, f"Request {i+1} should succeed, got {resp.status_code}"

    # 61st to 65th requests should return 429
    for i in range(60, 65):
        files = {"file": ("resume.pdf", b"%PDF-1.4 dummy content", "application/pdf")}
        resp = client.post("/upload", files=files)
        assert resp.status_code == 429, f"Request {i+1} should return 429, got {resp.status_code}"
        assert "Rate limit exceeded" in resp.json()["detail"]


@patch("src.api.read_resume", return_value="dummy resume text")
@patch("src.api.call_openai")
@patch("src.api.create_docx")
def test_rate_limiter_burst_on_tailor(mock_create_docx, mock_call_openai, mock_read_resume, client):
    """Bursting 65 requests on /resumes/{id}/tailor returns 429 after 60 requests."""
    mock_call_openai.return_value = {"name": "Test User"}
    mock_create_docx.return_value = b"dummy docx"

    # Create a dummy resume first with rate limit reset
    files = {"file": ("resume.pdf", b"%PDF-1.4 dummy content", "application/pdf")}
    upload_resp = client.post("/upload", files=files)
    assert upload_resp.status_code == 200
    resume_id = upload_resp.json()["id"]

    rate_limiter.reset()

    for i in range(60):
        resp = client.post(
            f"/resumes/{resume_id}/tailor",
            content="Software Engineer job description",
            headers={"Content-Type": "text/plain"}
        )
        assert resp.status_code == 200, f"Request {i+1} should succeed, got {resp.status_code}"

    # Exceeding request
    resp = client.post(
        f"/resumes/{resume_id}/tailor",
        content="Software Engineer job description",
        headers={"Content-Type": "text/plain"}
    )
    assert resp.status_code == 429
    assert "Rate limit exceeded" in resp.json()["detail"]


@patch("src.api.read_resume", return_value="dummy resume text")
@patch("src.api.call_openai_cover_letter")
@patch("src.api.create_cover_letter_docx")
def test_rate_limiter_burst_on_cover_letter(mock_create_cover_letter_docx, mock_call_openai_cover_letter, mock_read_resume, client):
    """Bursting on /resumes/{id}/cover-letter returns 429 after 60 requests."""
    mock_call_openai_cover_letter.return_value = {"name": "Test User", "content": "Dear Hiring Manager..."}
    mock_create_cover_letter_docx.return_value = b"dummy cover letter docx"

    # Create dummy resume
    files = {"file": ("resume.pdf", b"%PDF-1.4 dummy content", "application/pdf")}
    upload_resp = client.post("/upload", files=files)
    assert upload_resp.status_code == 200
    resume_id = upload_resp.json()["id"]

    rate_limiter.reset()

    for i in range(60):
        resp = client.post(
            f"/resumes/{resume_id}/cover-letter",
            content="Software Engineer job description",
            headers={"Content-Type": "text/plain"}
        )
        assert resp.status_code == 200

    resp = client.post(
        f"/resumes/{resume_id}/cover-letter",
        content="Software Engineer job description",
        headers={"Content-Type": "text/plain"}
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 4. TokenBucketRateLimiter Unit Tests & Idle IP Eviction
# ---------------------------------------------------------------------------

def test_token_bucket_replenishment():
    """Tokens should replenish over time according to rate."""
    limiter = TokenBucketRateLimiter(rate=2.0, per_seconds=1.0, idle_timeout=10.0)
    
    assert limiter.is_allowed("1.1.1.1") is True
    assert limiter.is_allowed("1.1.1.1") is True
    assert limiter.is_allowed("1.1.1.1") is False

    # Sleep 0.6s -> should replenish at least 1 token (rate = 2/sec)
    time.sleep(0.6)
    assert limiter.is_allowed("1.1.1.1") is True


def test_token_bucket_idle_ip_eviction():
    """Idle IP entries older than idle_timeout must be evicted from memory."""
    limiter = TokenBucketRateLimiter(rate=10.0, per_seconds=60.0, idle_timeout=0.2)
    
    limiter.is_allowed("10.0.0.1")
    limiter.is_allowed("10.0.0.2")
    assert "10.0.0.1" in limiter.buckets
    assert "10.0.0.2" in limiter.buckets

    # Wait for idle_timeout to pass
    time.sleep(0.25)

    # Next check for another IP or same IP should evict idle IPs
    limiter.is_allowed("10.0.0.3")
    assert "10.0.0.1" not in limiter.buckets
    assert "10.0.0.2" not in limiter.buckets
    assert "10.0.0.3" in limiter.buckets
