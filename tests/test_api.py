from datetime import datetime
from fastapi.testclient import TestClient
import pytest

from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint_success(client):
    """Test that /api/health returns 200 with valid structure."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert "timestamp" in data

    # Verify timestamp is a valid ISO-8601 UTC timestamp
    timestamp = datetime.fromisoformat(data["timestamp"])
    assert timestamp.tzinfo is not None


def test_root_endpoint(client):
    """Test root endpoint greeting."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Resume Tailor API, Go to /docs to get started"}


def test_get_resume_status_not_found(client):
    """Test getting status for non-existent resume returns 404."""
    response = client.get("/resumes/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Resume not found"


def test_upload_resume_invalid_file_extension(client):
    """Test uploading an unsupported file type returns 400."""
    response = client.post(
        "/upload",
        files={"file": ("test.txt", b"dummy content", "text/plain")}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "File must be .pdf or .docx"

