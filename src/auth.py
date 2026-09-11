"""Unified session handling and authentication utilities.

Provides cookie- and header-based token extraction, cryptographic JWT signing
and validation using standard HMAC-SHA256, user identity representation, and
FastAPI route guard dependencies for both web pages (redirecting with `next`)
and REST APIs (returning HTTP 401).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Secret key used for cryptographic signature verification.
# Configurable via environment variable; defaults to a deterministic internal secret.
SECRET_KEY: str = os.getenv("SECRET_KEY", "resume-maker-pricehawk-session-secret-orc-36")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REDIRECT_STATUS_CODE: int = status.HTTP_303_SEE_OTHER

security_bearer = HTTPBearer(auto_error=False)


# ============================================================================
# Exception Hierarchy
# ============================================================================

class AuthError(ValueError):
    """Base error for authentication failures."""
    pass


class TokenExpiredError(AuthError):
    """Raised when an authentication token has expired."""
    pass


class InvalidTokenError(AuthError):
    """Raised when an authentication token is malformed or has an invalid signature."""
    pass


# ============================================================================
# Schemas & Models
# ============================================================================

class CurrentUser(BaseModel):
    """Identity model representing an authenticated user session."""

    id: str = Field(..., description="Unique user identifier.")
    username: Optional[str] = Field(None, description="Username of the user.")
    email: Optional[str] = Field(None, description="Email address of the user.")
    role: Optional[str] = Field("user", description="Authorization role.")


class LoginRequest(BaseModel):
    """Payload for login requests."""

    username: Optional[str] = Field(None, description="Username.")
    email: Optional[str] = Field(None, description="Email address.")
    password: str = Field(..., description="Password.")
    next: Optional[str] = Field(None, description="Destination page after login.")


class AuthResponse(BaseModel):
    """Response payload for successful API login."""

    access_token: str
    token_type: str = "bearer"
    redirect_url: str = "/dashboard"
    user: Optional[dict[str, Any]] = None


# ============================================================================
# Pure-Python JWT Signing and Verification (RFC 7519 Compliant HS256)
# ============================================================================

def _b64url_encode(data: bytes) -> str:
    """Encode bytes to a base64url ASCII string without trailing padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Decode a base64url string back to bytes, re-adding required padding."""
    rem = len(s) % 4
    if rem != 0:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def encode_jwt(payload: dict[str, Any], secret: str = SECRET_KEY) -> str:
    """Encode payload into an HS256 signed JWT string."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    header_b64 = _b64url_encode(header_json)
    payload_b64 = _b64url_encode(payload_json)

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_jwt(token: str, secret: str = SECRET_KEY) -> dict[str, Any]:
    """Decode and verify an HS256 signed JWT string.

    Raises:
        InvalidTokenError: If token structure, decoding, or signature fails.
        TokenExpiredError: If the exp claim timestamp is in the past.
    """
    clean_token = token.strip()
    parts = clean_token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError("Token must contain 3 dot-separated segments.")

    header_b64, payload_b64, sig_b64 = parts

    # Signature verification
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        provided_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise InvalidTokenError(f"Malformed signature encoding: {exc}") from exc

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise InvalidTokenError("Signature verification failed.")

    # Payload extraction
    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise InvalidTokenError(f"Malformed payload JSON: {exc}") from exc

    # Expiry verification
    if "exp" in payload:
        exp_ts = payload["exp"]
        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts > exp_ts:
            raise TokenExpiredError("Token has expired.")

    return payload


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
    secret_key: Optional[str] = None,
) -> str:
    """Create a signed JWT access token with an expiration timestamp."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.setdefault("sub", str(to_encode.get("id") or to_encode.get("username") or "user_1"))
    to_encode["exp"] = int(expire.timestamp())
    to_encode["iat"] = int(now.timestamp())

    return encode_jwt(to_encode, secret_key or SECRET_KEY)


def create_expired_token(
    data: dict[str, Any],
    secret_key: Optional[str] = None,
) -> str:
    """Create an expired JWT token for automated testing of expiration handling."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now - timedelta(hours=1)
    to_encode.setdefault("sub", str(to_encode.get("id") or to_encode.get("username") or "user_1"))
    to_encode["exp"] = int(expire.timestamp())
    to_encode["iat"] = int((now - timedelta(hours=2)).timestamp())

    return encode_jwt(to_encode, secret_key or SECRET_KEY)


def verify_token_sync(token: str, secret_key: Optional[str] = None) -> CurrentUser:
    """Synchronously verify a token and construct CurrentUser."""
    if not token or not token.strip():
        raise InvalidTokenError("Token cannot be empty.")

    payload = decode_jwt(token, secret_key or SECRET_KEY)
    user_id = str(payload.get("sub") or payload.get("id") or "")
    if not user_id:
        raise InvalidTokenError("Token payload missing subject identifier.")

    username = payload.get("username") or user_id
    email = payload.get("email")
    role = payload.get("role", "user")

    return CurrentUser(
        id=user_id,
        username=username,
        email=email,
        role=role,
    )


async def verify_token_string(token: str) -> CurrentUser:
    """Asynchronously verify a token string (compatible with Supabase / Pricehawk interface)."""
    return verify_token_sync(token)


# ============================================================================
# Token Extraction & Unified Session Detection
# ============================================================================

def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract authentication token from Authorization header or browser cookies.

    Checks:
    1. HTTP Authorization header (Bearer <token> or raw token)
    2. X-Access-Token header
    3. Browser cookies: access_token, session_token, auth_token, session, token
    """
    # 1. Authorization header
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header:
        parts = auth_header.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            val = parts[1].strip()
            if val:
                return val
        elif len(parts) == 1:
            val = parts[0].strip()
            if val.lower().startswith("bearer "):
                val = val[7:].strip()
            if val:
                return val

    # 2. Custom header
    x_token = request.headers.get("X-Access-Token") or request.headers.get("x-access-token")
    if x_token and x_token.strip():
        return x_token.strip()

    # 3. Cookies
    cookie_names = ("access_token", "session_token", "auth_token", "session", "token")
    for cookie_name in cookie_names:
        cookie_val = request.cookies.get(cookie_name)
        if cookie_val:
            cleaned = cookie_val.strip()
            # Strip surrounding quotes if present
            if (cleaned.startswith('"') and cleaned.endswith('"')) or (
                cleaned.startswith("'") and cleaned.endswith("'")
            ):
                cleaned = cleaned[1:-1].strip()
            if cleaned.lower().startswith("bearer "):
                cleaned = cleaned[7:].strip()
            if cleaned:
                return cleaned

    return None


async def get_current_user_optional(
    request: Request,
) -> Tuple[Optional[CurrentUser], Optional[str]]:
    """Attempt user authentication without raising exceptions.

    Returns:
        (CurrentUser, None) on success.
        (None, "missing") if no token was provided.
        (None, "expired") if the token was found but expired.
        (None, "invalid") if the token was malformed or signature failed.
    """
    token = extract_token_from_request(request)
    if not token:
        return None, "missing"

    try:
        user = verify_token_sync(token)
        return user, None
    except TokenExpiredError:
        return None, "expired"
    except Exception as exc:
        logger.debug("Token validation failure: %s", exc)
        return None, "invalid"


# ============================================================================
# Route Guards / Dependencies
# ============================================================================

def sanitize_next_destination(destination: Optional[str]) -> str:
    """Prevent open-redirect vulnerabilities by restricting redirects to safe relative paths."""
    if not destination or not destination.strip():
        return "/dashboard"

    dest = destination.strip()
    # Reject protocol schemes (http:, https:, javascript:, data:)
    if ":" in dest:
        return "/dashboard"

    # Reject protocol-relative paths
    if dest.startswith("//"):
        return "/dashboard"

    # Must be an absolute-path relative URL
    if not dest.startswith("/"):
        return "/dashboard"

    return dest


async def require_page_auth(request: Request) -> CurrentUser:
    """Guard dependency for web page routes.

    Redirects unauthenticated or expired users to `/login?next=<destination>`
    preserving the exact destination route and query string.
    """
    user, error_reason = await get_current_user_optional(request)
    if user is not None:
        return user

    destination = request.url.path
    if request.url.query:
        destination = f"{destination}?{request.url.query}"

    safe_dest = sanitize_next_destination(destination)
    login_url = f"/login?next={quote(safe_dest, safe='/?&=')}"

    raise HTTPException(
        status_code=REDIRECT_STATUS_CODE,
        headers={"Location": login_url},
    )


async def require_api_auth(request: Request) -> CurrentUser:
    """Guard dependency for API routes.

    Always returns HTTP 401 Unauthorized with standardized error diagnostics
    when authentication is missing, expired, or invalid.
    """
    user, error_reason = await get_current_user_optional(request)
    if user is not None:
        return user

    if error_reason == "expired":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    elif error_reason == "invalid":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = None,
    request: Optional[Request] = None,
) -> CurrentUser:
    """Compatibility dependency matching standard FastAPI / Supabase get_current_user signature."""
    if request is not None:
        return await require_api_auth(request)
    if credentials is not None:
        return verify_token_sync(credentials.credentials)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
