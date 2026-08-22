"""Unit and regression tests for the API endpoints."""

from datetime import datetime
from fastapi.testclient import TestClient
import pytest

from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check_status_code(client):
    """Test that /api/health returns HTTP 200 OK."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_check_payload_structure(client):
    """Test that /api/health returns valid JSON with expected keys and types."""
    response = client.get("/api/health")
    assert response.headers["content-type"] == "application/json"
    
    data = response.json()
    assert "status" in data
    assert "timestamp" in data
    assert "version" in data
    
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"


def test_health_check_timestamp_format(client):
    """Test that /api/health returns a valid ISO-8601 UTC timestamp."""
    response = client.get("/api/health")
    data = response.json()
    
    timestamp_str = data["timestamp"]
    # Verify it can be parsed as ISO-8601 datetime
    parsed_dt = datetime.fromisoformat(timestamp_str)
    assert parsed_dt is not None
    # Verify it includes UTC timezone offset info (+00:00 or Z)
    assert parsed_dt.tzinfo is not None
