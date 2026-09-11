"""Pytest fixtures for API and page route tests."""

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.auth import create_access_token


@pytest.fixture
def client():
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    """Auth headers for testing."""
    token = create_access_token({"sub": "testuser", "username": "testuser", "email": "test@example.com"})
    return {"Authorization": f"Bearer {token}"}
