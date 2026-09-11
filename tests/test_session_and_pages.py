"""Automated tests for unified session handling and protected page redirection.

Verifies:
1. Browser cookies and Authorization headers are seamlessly recognized for authentication.
2. Unauthenticated and expired users visiting protected pages are redirected to /login with `next`.
3. Destination query parameters are preserved in the `next` parameter.
4. Successful login smoothly forwards the user to their intended destination and sets auth cookies.
5. Unauthenticated page access yields HTTP 302/303 redirect while API routes yield HTTP 401.
6. Open-redirect prevention sanitizes malicious external redirect targets.
"""

from typing import Generator
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.auth import (
    create_access_token,
    create_expired_token,
    verify_token_string,
    verify_token_sync,
    CurrentUser,
)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide isolated FastAPI TestClient instance."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_token() -> str:
    """Generate a valid signed access token."""
    return create_access_token({"sub": "testuser", "username": "testuser", "email": "test@example.com"})


@pytest.fixture
def expired_token() -> str:
    """Generate an expired signed access token."""
    return create_expired_token({"sub": "testuser", "username": "testuser", "email": "test@example.com"})


# ============================================================================
# 1. Protected Pages Require Auth & Redirect with `next` (HTTP 302/303)
# ============================================================================

@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/settings",
        "/account/settings",
        "/alerts/settings",
        "/tracked",
        "/discover",
        "/insights",
    ],
)
def test_unauthenticated_page_redirects_with_next_param(client: TestClient, path: str):
    """Unauthenticated users visiting protected pages must be redirected to /login?next=<path>."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "location" in response.headers
    assert response.headers["location"] == f"/login?next={path}"


def test_unauthenticated_page_preserves_query_parameters(client: TestClient):
    """Query parameters on destination pages must be preserved in the `next` redirect."""
    response = client.get("/settings?tab=security&theme=dark", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login?next=/settings?tab=security&theme=dark"


def test_expired_token_in_cookie_redirects_to_login(client: TestClient, expired_token: str):
    """Users with expired cookies visiting protected pages must be redirected to /login with `next`."""
    client.cookies.set("access_token", expired_token)
    response = client.get(
        "/dashboard",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login?next=/dashboard"


def test_expired_token_in_header_redirects_to_login(client: TestClient, expired_token: str):
    """Users with expired Authorization header visiting protected pages must be redirected to /login."""
    response = client.get(
        "/settings",
        headers={"Authorization": f"Bearer {expired_token}"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login?next=/settings"


def test_malformed_token_redirects_to_login(client: TestClient):
    """Users with malformed or tampered tokens visiting protected pages must redirect to /login."""
    client.cookies.set("access_token", "invalid.jwt.signature")
    response = client.get(
        "/dashboard",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login?next=/dashboard"


# ============================================================================
# 2. Unified Session Handling: Recognition of Cookies & Headers
# ============================================================================

def test_page_access_with_access_token_cookie(client: TestClient, valid_token: str):
    """Protected pages must seamlessly recognize authentication from `access_token` cookie."""
    client.cookies.set("access_token", valid_token)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Dashboard" in response.text
    assert "testuser" in response.text


def test_page_access_with_session_token_cookie(client: TestClient, valid_token: str):
    """Protected pages must seamlessly recognize authentication from `session_token` cookie."""
    client.cookies.set("session_token", valid_token)
    response = client.get("/settings")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Settings" in response.text


def test_page_access_with_bearer_authorization_header(client: TestClient, valid_token: str):
    """Protected pages must seamlessly recognize authentication from Authorization Bearer header."""
    response = client.get(
        "/dashboard",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Dashboard" in response.text


def test_page_access_with_raw_token_authorization_header(client: TestClient, valid_token: str):
    """Protected pages must recognize Authorization header without Bearer prefix."""
    response = client.get(
        "/settings",
        headers={"Authorization": valid_token},
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_page_access_with_quoted_cookie(client: TestClient, valid_token: str):
    """Protected pages must handle quoted cookies gracefully."""
    client.cookies.set("access_token", f'"{valid_token}"')
    response = client.get("/account/settings")
    assert response.status_code == 200
    assert "Account Settings" in response.text


# ============================================================================
# 3. API Routes Return HTTP 401 (Never 302/303 Redirect)
# ============================================================================

@pytest.mark.parametrize(
    "api_path",
    [
        "/api/dashboard/stats",
        "/api/dashboard/activity",
        "/api/dashboard/products",
        "/api/insights",
        "/api/settings",
        "/api/account/settings",
        "/api/alerts/settings",
        "/api/user",
        "/api/me",
        "/api/auth/me",
    ],
)
def test_unauthenticated_api_routes_return_401(client: TestClient, api_path: str):
    """Unauthenticated access to API routes must always return HTTP 401 Unauthorized, not redirects."""
    response = client.get(api_path, follow_redirects=False)
    assert response.status_code == 401
    assert "application/json" in response.headers["content-type"]
    data = response.json()
    assert "detail" in data


def test_expired_token_on_api_route_returns_401(client: TestClient, expired_token: str):
    """Expired token on API routes must return HTTP 401 Unauthorized."""
    response = client.get(
        "/api/dashboard/stats",
        headers={"Authorization": f"Bearer {expired_token}"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    data = response.json()
    assert "expired" in data["detail"].lower()


def test_authenticated_api_route_via_cookie(client: TestClient, valid_token: str):
    """API routes must recognize authentication from cookies."""
    client.cookies.set("access_token", valid_token)
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["user_id"] == "testuser"


def test_authenticated_api_route_via_header(client: TestClient, valid_token: str):
    """API routes must recognize authentication from Authorization header."""
    response = client.get(
        "/api/settings",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["user_id"] == "testuser"


# ============================================================================
# 4. Login Flow & Destination Forwarding
# ============================================================================

def test_login_page_renders_html_with_form(client: TestClient):
    """GET /login must return HTML login page containing login form."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PriceHawk" in response.text
    assert "<form" in response.text


def test_authenticated_user_visiting_login_redirects_to_destination(client: TestClient, valid_token: str):
    """Already authenticated user visiting GET /login?next=/settings redirects to /settings."""
    client.cookies.set("access_token", valid_token)
    response = client.get(
        "/login?next=/settings",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/settings"


def test_login_post_form_forwards_to_intended_destination(client: TestClient):
    """POST /login with form data must forward user to next destination and set auth cookies."""
    response = client.post(
        "/login",
        data={"username": "alice", "password": "password123", "next": "/settings"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/settings"
    assert "access_token" in response.cookies
    assert "session_token" in response.cookies


def test_login_post_json_forwards_to_intended_destination(client: TestClient):
    """POST /login with JSON payload must forward user to next destination."""
    response = client.post(
        "/login",
        json={"username": "bob", "password": "password123", "next": "/account/settings"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/account/settings"
    assert "access_token" in response.cookies


def test_login_post_default_destination_is_dashboard(client: TestClient):
    """POST /login without next specified defaults to /dashboard."""
    response = client.post(
        "/login",
        data={"username": "charlie", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/dashboard"


def test_login_full_redirect_chain(client: TestClient):
    """Full browser test: login redirect chain followed seamlessly to protected page."""
    response = client.post(
        "/login",
        data={"username": "david", "password": "password123", "next": "/settings"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Settings" in response.text
    assert "david" in response.text


def test_login_invalid_credentials(client: TestClient):
    """POST /login with empty credentials must return 401."""
    response = client.post(
        "/login",
        data={"username": "", "password": ""},
        follow_redirects=False,
    )
    assert response.status_code == 401


# ============================================================================
# 5. Open-Redirect Vulnerability Prevention
# ============================================================================

@pytest.mark.parametrize(
    "malicious_next",
    [
        "https://evil.com/phishing",
        "http://attacker.com",
        "//evil.com",
        "javascript:alert(1)",
    ],
)
def test_login_sanitizes_external_redirects(client: TestClient, malicious_next: str):
    """Open redirect attempts must be sanitized to fallback to /dashboard."""
    response = client.post(
        "/login",
        data={"username": "alice", "password": "password123", "next": malicious_next},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/dashboard"


# ============================================================================
# 6. Logout Clears Session Cookies
# ============================================================================

def test_logout_clears_cookies_and_redirects(client: TestClient, valid_token: str):
    """Logout endpoint must clear cookies and redirect to /login."""
    client.cookies.set("access_token", valid_token)
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login"


# ============================================================================
# 7. Helper & Interface Compatibility Tests
# ============================================================================

@pytest.mark.asyncio
async def test_verify_token_string_async(valid_token: str):
    """verify_token_string must return CurrentUser instance."""
    user = await verify_token_string(valid_token)
    assert isinstance(user, CurrentUser)
    assert user.id == "testuser"
    assert user.username == "testuser"


def test_verify_token_sync(valid_token: str):
    """verify_token_sync must synchronously return CurrentUser instance."""
    user = verify_token_sync(valid_token)
    assert isinstance(user, CurrentUser)
    assert user.id == "testuser"
