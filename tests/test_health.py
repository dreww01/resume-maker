"""Unit tests for the /api/health endpoint."""

from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest

from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check_status_code(client):
    """Test that GET /api/health returns HTTP 200 OK."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_check_payload_structure(client):
    """Test that /api/health returns valid JSON with exact expected schema."""
    response = client.get("/api/health")
    assert response.headers["content-type"] == "application/json"

    data = response.json()
    assert isinstance(data, dict)
    assert set(data.keys()) == {"status", "timestamp", "version"}
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"


def test_health_check_timestamp_validity(client):
    """Test that /api/health returns a valid ISO-8601 UTC timestamp reflecting current time."""
    before = datetime.now(timezone.utc)
    response = client.get("/api/health")
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    data = response.json()

    timestamp_str = data["timestamp"]
    parsed_dt = datetime.fromisoformat(timestamp_str)

    assert parsed_dt.tzinfo is not None
    assert before <= parsed_dt <= after
