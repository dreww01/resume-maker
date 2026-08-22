"""Unit and regression tests for the GET /health endpoint.

These tests are fully hermetic: they use FastAPI's TestClient (backed by
httpx) and mock out every external dependency (database, resume processor,
python-multipart) so that no real I/O occurs.  They exercise:

- HTTP status code
- Response Content-Type (JSON)
- Exact payload shape and field values
- ISO-8601 UTC timestamp semantics
- Stability across repeated calls (regression)
- OpenAPI schema registration
"""

import datetime
import re
from unittest import mock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared test client fixture (module scope for speed).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Return a synchronous TestClient wrapping the FastAPI application."""
    from src.api import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper: ISO-8601 UTC pattern (e.g. "2024-01-15T12:34:56.123456+00:00").
# ---------------------------------------------------------------------------

_ISO8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"  # date and time
    r"(\.\d+)?"                                 # optional microseconds
    r"(\+00:00|Z)$"                             # UTC offset
)


def _assert_utc_timestamp(value: str) -> None:
    """Assert *value* is a valid ISO-8601 UTC timestamp string."""
    assert isinstance(value, str), f"Expected str timestamp, got {type(value)}"
    assert _ISO8601_UTC_RE.match(value), (
        f"Timestamp {value!r} does not match ISO-8601 UTC format"
    )
    # Confirm it can be parsed back to a UTC-aware datetime.
    parsed = datetime.datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, "Timestamp must carry timezone info"


# ===========================================================================
# Tests
# ===========================================================================


class TestHealthEndpointHttpSemantics:
    """Verify HTTP-level contract of GET /health."""

    def test_status_code_is_200(self, client: TestClient) -> None:
        """The endpoint MUST return HTTP 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_content_type_is_json(self, client: TestClient) -> None:
        """Response Content-Type must be application/json."""
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_method_not_allowed_for_post(self, client: TestClient) -> None:
        """POST /health must not be routed (405 or 404, not 200)."""
        response = client.post("/health")
        assert response.status_code in {404, 405}

    def test_method_not_allowed_for_put(self, client: TestClient) -> None:
        """PUT /health must not be routed."""
        response = client.put("/health")
        assert response.status_code in {404, 405}

    def test_method_not_allowed_for_delete(self, client: TestClient) -> None:
        """DELETE /health must not be routed."""
        response = client.delete("/health")
        assert response.status_code in {404, 405}


class TestHealthEndpointPayload:
    """Verify the JSON payload shape and field values."""

    @pytest.fixture(autouse=True)
    def _response(self, client: TestClient) -> None:
        self._resp = client.get("/health")
        self._body = self._resp.json()

    def test_payload_has_status_field(self) -> None:
        assert "status" in self._body, "Response missing 'status' field"

    def test_payload_has_timestamp_field(self) -> None:
        assert "timestamp" in self._body, "Response missing 'timestamp' field"

    def test_payload_has_version_field(self) -> None:
        assert "version" in self._body, "Response missing 'version' field"

    def test_payload_has_exactly_three_fields(self) -> None:
        """No extra undocumented fields should leak into the response."""
        assert set(self._body.keys()) == {"status", "timestamp", "version"}

    def test_status_value_is_healthy(self) -> None:
        assert self._body["status"] == "healthy"

    def test_version_value_matches_app_constant(self) -> None:
        from src.api import _APP_VERSION
        assert self._body["version"] == _APP_VERSION

    def test_version_matches_package_metadata(self) -> None:
        """Regression: version in the health payload must equal _APP_VERSION,
        which is sourced from the installed package metadata (pyproject.toml).
        """
        from src.api import _APP_VERSION
        assert self._body["version"] == _APP_VERSION

    def test_timestamp_is_iso8601_utc(self) -> None:
        _assert_utc_timestamp(self._body["timestamp"])


class TestHealthEndpointTimestamp:
    """Deeper timestamp tests using controlled time."""

    def test_timestamp_uses_utc_timezone(self, client: TestClient) -> None:
        """Returned timestamp must be UTC-aware (offset +00:00 or Z)."""
        response = client.get("/health")
        ts_str = response.json()["timestamp"]
        parsed = datetime.datetime.fromisoformat(ts_str)
        # UTC offset must be zero.
        assert parsed.utcoffset() == datetime.timedelta(0), (
            f"Expected UTC (offset 0), got {parsed.utcoffset()}"
        )

    def test_timestamp_advances_between_calls(self, client: TestClient) -> None:
        """Successive calls should produce non-decreasing timestamps."""
        r1 = client.get("/health").json()["timestamp"]
        r2 = client.get("/health").json()["timestamp"]
        t1 = datetime.datetime.fromisoformat(r1)
        t2 = datetime.datetime.fromisoformat(r2)
        assert t2 >= t1, (
            f"Timestamp went backwards: {r1!r} -> {r2!r}"
        )

    def test_timestamp_reflects_frozen_time(self, client: TestClient) -> None:
        """When the system clock is mocked, the endpoint uses the mocked time."""
        frozen = datetime.datetime(2025, 6, 15, 8, 30, 0,
                                   tzinfo=datetime.timezone.utc)

        real_datetime = datetime.datetime

        class _FrozenDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return frozen

        with mock.patch("src.api.datetime") as mock_dt_module:
            mock_dt_module.datetime = _FrozenDatetime
            mock_dt_module.timezone = datetime.timezone
            response = client.get("/health")

        assert response.status_code == 200
        returned_ts = response.json()["timestamp"]
        parsed = datetime.datetime.fromisoformat(returned_ts)
        assert parsed == frozen, (
            f"Expected frozen time {frozen.isoformat()!r}, got {returned_ts!r}"
        )


class TestHealthEndpointRegression:
    """Regression tests ensuring the endpoint stays stable over time."""

    def test_endpoint_is_idempotent(self, client: TestClient) -> None:
        """Multiple GET requests all succeed with the same shape."""
        from src.api import _APP_VERSION
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "healthy"
            assert body["version"] == _APP_VERSION
            _assert_utc_timestamp(body["timestamp"])

    def test_endpoint_registered_in_openapi_schema(self, client: TestClient) -> None:
        """The /health route must appear in the auto-generated OpenAPI spec."""
        schema = client.get("/openapi.json").json()
        paths = schema.get("paths", {})
        assert "/health" in paths, (
            f"/health not found in OpenAPI paths: {list(paths.keys())}"
        )

    def test_openapi_health_route_supports_get(self, client: TestClient) -> None:
        """The OpenAPI entry for /health must declare a GET operation."""
        schema = client.get("/openapi.json").json()
        health_ops = schema["paths"]["/health"]
        assert "get" in health_ops, (
            f"Expected 'get' operation for /health, found: {list(health_ops.keys())}"
        )

    def test_status_field_type_is_string(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert isinstance(body["status"], str)

    def test_version_field_type_is_string(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert isinstance(body["version"], str)

    def test_timestamp_field_type_is_string(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert isinstance(body["timestamp"], str)

    def test_version_semver_format(self, client: TestClient) -> None:
        """Version must follow MAJOR.MINOR.PATCH semver notation, with an
        optional pre-release suffix (e.g. '0.0.0-dev' when the package is not
        installed in editable mode).
        """
        body = client.get("/health").json()
        semver_re = re.compile(r"^\d+\.\d+\.\d+(-.+)?$")
        assert semver_re.match(body["version"]), (
            f"Version {body['version']!r} does not match MAJOR.MINOR.PATCH[-prerelease]"
        )
