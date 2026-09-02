import io
import os
import time
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-dummy-openai-key")

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.security import (
    TokenBucketRateLimiter,
    rate_limiter,
    MAX_REQUEST_BODY_SIZE,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset global rate limiter state before each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# 1. Security Response Headers Middleware Tests
# ============================================================================

def test_security_headers_present_on_successful_response(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_present_on_not_found(client):
    response = client.get("/resumes/999999")
    assert response.status_code == 404
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_present_on_bad_request(client):
    # Upload invalid file extension (.txt)
    response = client.post(
        "/upload",
        files={"file": ("test.txt", io.BytesIO(b"dummy text"), "text/plain")}
    )
    assert response.status_code == 400
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_present_on_413_payload_too_large(client):
    headers = {"Content-Length": str(MAX_REQUEST_BODY_SIZE + 1024)}
    response = client.post("/upload", headers=headers, content=b"dummy")
    assert response.status_code == 413
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


def test_security_headers_present_on_429_too_many_requests(client):
    # Exhaust rate limit
    ip_headers = {"X-Forwarded-For": "192.168.1.50"}
    for _ in range(60):
        client.post(
            "/upload",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
            headers=ip_headers,
        )
    # 61st request triggers 429
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        headers=ip_headers,
    )
    assert response.status_code == 429
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


# ============================================================================
# 2. Request Body Size Limit Middleware Tests
# ============================================================================

def test_request_payload_exceeding_5mb_returns_413(client):
    # Content-Length exceeds 5MB
    large_size = 5 * 1024 * 1024 + 1
    response = client.post(
        "/upload",
        headers={"Content-Length": str(large_size)},
        content=b"x"
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Payload Too Large"}


def test_request_payload_under_5mb_is_accepted(client):
    # Valid small upload under 5MB
    pdf_content = b"%PDF-1.4 " + b"a" * 1024
    response = client.post(
        "/upload",
        files={"file": ("resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert response.status_code == 200
    assert "id" in response.json()


# ============================================================================
# 3. Rate Limiter Tests
# ============================================================================

def test_burst_65_requests_on_upload_returns_429_after_60(client):
    ip_headers = {"X-Forwarded-For": "203.0.113.10"}
    pdf_content = b"%PDF-1.4 minimal"

    allowed_count = 0
    rejected_count = 0

    for i in range(65):
        response = client.post(
            "/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            headers=ip_headers,
        )
        if response.status_code == 200:
            allowed_count += 1
        elif response.status_code == 429:
            rejected_count += 1

    assert allowed_count == 60
    assert rejected_count == 5


def test_burst_65_requests_on_tailor_returns_429_after_60(client):
    ip_headers = {"X-Forwarded-For": "203.0.113.20"}

    # Mock the resume processor and database calls
    with patch("src.api.get_resume", return_value={"file_content": b"fake", "original_filename": "test.pdf"}), \
         patch("src.api.update_resume", return_value=True), \
         patch("src.api.read_resume", return_value="Resume text"), \
         patch("src.api.call_openai", return_value={"name": "Alice"}), \
         patch("src.api.create_docx", return_value=b"docx"):

        allowed_count = 0
        rejected_count = 0

        for i in range(65):
            response = client.post(
                "/resumes/1/tailor",
                content="Job description text",
                headers={"Content-Type": "text/plain", **ip_headers},
            )
            if response.status_code == 200:
                allowed_count += 1
            elif response.status_code == 429:
                rejected_count += 1

        assert allowed_count == 60
        assert rejected_count == 5


def test_burst_65_requests_on_cover_letter_returns_429_after_60(client):
    ip_headers = {"X-Forwarded-For": "203.0.113.30"}

    with patch("src.api.get_resume", return_value={"file_content": b"fake", "original_filename": "test.pdf"}), \
         patch("src.api.update_resume", return_value=True), \
         patch("src.api.read_resume", return_value="Resume text"), \
         patch("src.api.call_openai_cover_letter", return_value={"name": "Alice", "content": "Dear Hiring Manager"}), \
         patch("src.api.create_cover_letter_docx", return_value=b"docx"):

        allowed_count = 0
        rejected_count = 0

        for i in range(65):
            response = client.post(
                "/resumes/1/cover-letter",
                content="Job description text",
                headers={"Content-Type": "text/plain", **ip_headers},
            )
            if response.status_code == 200:
                allowed_count += 1
            elif response.status_code == 429:
                rejected_count += 1

        assert allowed_count == 60
        assert rejected_count == 5


def test_rate_limiter_distinct_clients():
    limiter = TokenBucketRateLimiter(rate=5, per=60.0)

    # Client A consumes all 5 tokens
    for _ in range(5):
        assert limiter.is_allowed("1.1.1.1", now=100.0) is True
    assert limiter.is_allowed("1.1.1.1", now=100.0) is False

    # Client B still has all 5 tokens
    for _ in range(5):
        assert limiter.is_allowed("2.2.2.2", now=100.0) is True
    assert limiter.is_allowed("2.2.2.2", now=100.0) is False


def test_rate_limiter_token_refill():
    limiter = TokenBucketRateLimiter(rate=60, per=60.0)  # 1 token / second

    # Consume all 60 tokens at t=0
    for _ in range(60):
        assert limiter.is_allowed("10.0.0.1", now=0.0) is True
    assert limiter.is_allowed("10.0.0.1", now=0.0) is False

    # After 1.5 seconds, 1 token refilled
    assert limiter.is_allowed("10.0.0.1", now=1.5) is True
    assert limiter.is_allowed("10.0.0.1", now=1.5) is False

    # After 10 seconds, 10 tokens refilled
    for _ in range(10):
        assert limiter.is_allowed("10.0.0.1", now=11.5) is True
    assert limiter.is_allowed("10.0.0.1", now=11.5) is False


def test_rate_limiter_idle_ip_eviction():
    limiter = TokenBucketRateLimiter(rate=60, per=60.0, idle_timeout=60.0, cleanup_interval=60.0)

    # Add entries for multiple clients at t=100
    limiter.is_allowed("10.0.0.1", now=100.0)
    limiter.is_allowed("10.0.0.2", now=100.0)
    limiter.is_allowed("10.0.0.3", now=150.0)

    assert len(limiter.buckets) == 3

    # At t=170:
    # 10.0.0.1 was last updated at 100 (idle for 70s >= 60s) -> should be evicted
    # 10.0.0.2 was last updated at 100 (idle for 70s >= 60s) -> should be evicted
    # 10.0.0.3 was last updated at 150 (idle for 20s < 60s) -> should remain
    evicted = limiter.evict_idle(idle_timeout=60.0, now=170.0)

    assert evicted == 2
    assert "10.0.0.1" not in limiter.buckets
    assert "10.0.0.2" not in limiter.buckets
    assert "10.0.0.3" in limiter.buckets


def test_automatic_eviction_during_request():
    limiter = TokenBucketRateLimiter(rate=60, per=60.0, idle_timeout=60.0, cleanup_interval=60.0)

    # Initial request at t=0
    limiter.is_allowed("10.0.0.1", now=0.0)
    assert "10.0.0.1" in limiter.buckets

    # Request from new client at t=65 (cleanup_interval 60 has elapsed)
    limiter.is_allowed("10.0.0.2", now=65.0)

    # 10.0.0.1 was idle for 65s and should be automatically evicted during the cleanup cycle
    assert "10.0.0.1" not in limiter.buckets
    assert "10.0.0.2" in limiter.buckets


def test_root_endpoint_not_rate_limited(client):
    ip_headers = {"X-Forwarded-For": "203.0.113.99"}
    for _ in range(70):
        response = client.get("/", headers=ip_headers)
        assert response.status_code == 200


def test_rate_limiter_extracts_x_real_ip(client):
    ip_headers = {"X-Real-IP": "198.51.100.25"}
    for _ in range(60):
        response = client.post(
            "/upload",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
            headers=ip_headers,
        )
        assert response.status_code == 200

    # 61st request is blocked
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        headers=ip_headers,
    )
    assert response.status_code == 429


def test_request_payload_exact_5mb_boundary(client):
    # Exactly 5MB should pass the middleware check (not return 413)
    headers = {"Content-Length": str(MAX_REQUEST_BODY_SIZE), "Content-Type": "text/plain"}
    response = client.post("/resumes/999/tailor", headers=headers, content="sample job description")
    # Resume 999 does not exist, so it returns 404 (or processes), but definitely not 413
    assert response.status_code == 404
    assert response.status_code != 413


def test_malformed_content_length_header(client):
    headers = {"Content-Length": "not-a-number"}
    response = client.get("/", headers=headers)
    assert response.status_code == 200
