from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check_status_code(client):
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_check_payload_structure(client):
    response = client.get("/api/health")
    data = response.json()

    assert "status" in data
    assert "timestamp" in data
    assert "version" in data

    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"


def test_health_check_timestamp_is_iso8601_utc(client):
    response = client.get("/api/health")
    data = response.json()

    parsed_dt = datetime.fromisoformat(data["timestamp"])
    assert parsed_dt.tzinfo is not None, "timestamp must be timezone-aware ISO-8601"
    assert parsed_dt.utcoffset() == timedelta(0), "timestamp must be expressed in UTC"

    # The reported time must track the real clock, not a frozen or bogus value.
    now = datetime.now(timezone.utc)
    assert abs(now - parsed_dt) < timedelta(seconds=5), (
        f"timestamp drifted from wall clock: {data['timestamp']} vs {now.isoformat()}"
    )


def test_health_check_response_headers(client):
    response = client.get("/api/health")
    assert response.headers["content-type"].startswith("application/json")
