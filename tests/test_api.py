"""Unit and regression tests for API endpoints."""

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)


def test_root_endpoint():
    """Test the root endpoint returns a 200 OK status and welcome message."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data


def test_health_check_status_code():
    """Test that GET /api/health returns HTTP 200 OK with application/json."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


def test_health_check_payload_keys():
    """Test that GET /api/health payload contains the exact expected keys."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    assert set(data.keys()) == {"status", "timestamp", "version"}


def test_health_check_field_values_and_types():
    """Test that GET /api/health returns expected field values and types."""
    before_call = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = client.get("/api/health")
    after_call = datetime.now(timezone.utc) + timedelta(seconds=1)

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data["status"], str)
    assert data["status"] == "healthy"

    assert isinstance(data["version"], str)
    assert data["version"] == "1.0.0"

    assert isinstance(data["timestamp"], str)
    parsed_timestamp = datetime.fromisoformat(data["timestamp"])
    assert parsed_timestamp.tzinfo is not None
    assert before_call <= parsed_timestamp <= after_call


def test_health_check_hermetic_and_idempotent():
    """Test that GET /api/health can be invoked repeatedly without side effects."""
    for _ in range(5):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        parsed = datetime.fromisoformat(data["timestamp"])
        assert parsed.tzinfo is not None
