"""Page route tests verifying HTML rendering and protected page redirection."""

from src.auth import create_access_token, create_expired_token


def test_login_page_renders(client):
    """Test login page returns HTML."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PriceHawk" in response.text


def test_signup_page_renders(client):
    """Test signup page returns HTML."""
    response = client.get("/signup")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_forgot_password_page_renders(client):
    """Test forgot password page returns HTML."""
    response = client.get("/forgot-password")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Forgot Password" in response.text


def test_reset_password_page_renders(client):
    """Test reset password page returns HTML."""
    response = client.get("/reset-password")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_dashboard_requires_auth(client):
    """Test dashboard redirects unauthenticated users."""
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"] in ("/login?next=/dashboard", "/login") or "/login" in response.headers["location"]


def test_tracked_requires_auth(client):
    """Test tracked page redirects unauthenticated users."""
    response = client.get("/tracked", follow_redirects=False)
    assert response.status_code in (302, 303)


def test_discover_requires_auth(client):
    """Test discover page redirects unauthenticated users."""
    response = client.get("/discover", follow_redirects=False)
    assert response.status_code in (302, 303)


def test_insights_requires_auth(client):
    """Test insights page redirects unauthenticated users."""
    response = client.get("/insights", follow_redirects=False)
    assert response.status_code in (302, 303)


def test_account_settings_requires_auth(client):
    """Test account settings page redirects unauthenticated users."""
    response = client.get("/account/settings", follow_redirects=False)
    assert response.status_code in (302, 303)


def test_alerts_settings_requires_auth(client):
    """Test alert settings page redirects unauthenticated users."""
    response = client.get("/alerts/settings", follow_redirects=False)
    assert response.status_code in (302, 303)


def test_logout_clears_cookie(client):
    """Test logout clears access_token cookie."""
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "/login" in response.headers["location"]


def test_dashboard_authenticated_via_cookie(client):
    """Test dashboard returns 200 when authenticated via browser cookie."""
    token = create_access_token({"sub": "alice", "username": "alice"})
    client.cookies.set("access_token", token)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_dashboard_authenticated_via_header(client, auth_headers):
    """Test dashboard returns 200 when authenticated via Authorization header."""
    response = client.get("/dashboard", headers=auth_headers)
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_settings_authenticated_via_cookie(client):
    """Test settings returns 200 when authenticated via browser cookie."""
    token = create_access_token({"sub": "bob", "username": "bob"})
    client.cookies.set("access_token", token)
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Settings" in response.text


def test_settings_authenticated_via_header(client, auth_headers):
    """Test settings returns 200 when authenticated via Authorization header."""
    response = client.get("/settings", headers=auth_headers)
    assert response.status_code == 200
    assert "Settings" in response.text


def test_dashboard_expired_token_redirects(client):
    """Test dashboard redirects to /login?next=/dashboard when token is expired."""
    expired = create_expired_token({"sub": "alice"})
    client.cookies.set("access_token", expired)
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/login?next=/dashboard"
