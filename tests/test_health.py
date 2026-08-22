"""Unit and regression tests for the GET /api/health endpoint.

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
import sys
from types import ModuleType
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Pre-import mocking: stub out all heavy / unavailable dependencies BEFORE
# the application module is imported so the test process needs no external
# services, credentials, or optional C-extensions.
# ---------------------------------------------------------------------------

def _make_module_stub(name: str, **attrs) -> ModuleType:
    """Return a minimal module stub with permissive attribute access.

    Any attribute not explicitly provided via *attrs* is a fresh MagicMock,
    so ``from stub_module import anything`` always succeeds.
    """
    mod = ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)

    _fallback = mock.MagicMock()

    class _AutoAttrModule(ModuleType):
        def __getattr__(self, item: str):  # type: ignore[override]
            if item.startswith("__"):
                raise AttributeError(item)
            return getattr(_fallback, item)

    proxy = _AutoAttrModule(name)
    for k, v in attrs.items():
        setattr(proxy, k, v)
    return proxy


# python-multipart — FastAPI's ensure_multipart_is_installed() imports
# python_multipart.__version__ and asserts it is > "0.0.12".
# Starlette also tries ``from python_multipart.multipart import
# parse_options_header``.  Both paths must succeed.
_pm_version = "0.0.20"  # satisfies the > "0.0.12" assertion

_pm_multipart_stub = _make_module_stub(
    "python_multipart.multipart",
    parse_options_header=mock.MagicMock(),
)
_pm_stub = _make_module_stub(
    "python_multipart",
    __version__=_pm_version,
    multipart=_pm_multipart_stub,
)

for _mod_name, _stub in [
    ("python_multipart", _pm_stub),
    ("python_multipart.multipart", _pm_multipart_stub),
    ("multipart", _make_module_stub("multipart", __version__=_pm_version)),
    ("multipart.multipart", _make_module_stub(
        "multipart.multipart",
        parse_options_header=mock.MagicMock(),
    )),
]:
    sys.modules.setdefault(_mod_name, _stub)

# Application-internal modules with real I/O.
sys.modules.setdefault("src.database", _make_module_stub("src.database"))
sys.modules.setdefault("src.resume_processor", _make_module_stub("src.resume_processor"))

# Now safe to import the FastAPI app.
from src.api import _APP_VERSION, app  # noqa: E402  (intentional late import)

from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# Shared test client fixture (module scope for speed).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Return a synchronous TestClient wrapping the FastAPI application."""
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
    """Verify HTTP-level contract of GET /api/health."""

    def test_status_code_is_200(self, client: TestClient) -> None:
        """The endpoint MUST return HTTP 200 OK."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_content_type_is_json(self, client: TestClient) -> None:
        """Response Content-Type must be application/json."""
        response = client.get("/api/health")
        assert "application/json" in response.headers["content-type"]

    def test_method_not_allowed_for_post(self, client: TestClient) -> None:
        """POST /api/health must not be routed (405 or 404, not 200)."""
        response = client.post("/api/health")
        assert response.status_code in {404, 405}

    def test_method_not_allowed_for_put(self, client: TestClient) -> None:
        """PUT /api/health must not be routed."""
        response = client.put("/api/health")
        assert response.status_code in {404, 405}

    def test_method_not_allowed_for_delete(self, client: TestClient) -> None:
        """DELETE /api/health must not be routed."""
        response = client.delete("/api/health")
        assert response.status_code in {404, 405}


class TestHealthEndpointPayload:
    """Verify the JSON payload shape and field values."""

    @pytest.fixture(autouse=True)
    def _response(self, client: TestClient) -> None:
        self._resp = client.get("/api/health")
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
        assert self._body["version"] == _APP_VERSION

    def test_version_is_1_0_0(self) -> None:
        """Regression: version must be '1.0.0' per the issue specification."""
        assert self._body["version"] == "1.0.0"

    def test_timestamp_is_iso8601_utc(self) -> None:
        _assert_utc_timestamp(self._body["timestamp"])

    def test_timestamp_is_close_to_now(self) -> None:
        """Timestamp should be within 5 seconds of the test's clock."""
        now = datetime.datetime.now(datetime.timezone.utc)
        ts = datetime.datetime.fromisoformat(self._body["timestamp"])
        delta = abs((now - ts).total_seconds())
        assert delta < 5, (
            f"Timestamp {self._body['timestamp']!r} is {delta:.1f}s away from now"
        )


class TestHealthEndpointTimestamp:
    """Deeper timestamp tests using controlled time."""

    def test_timestamp_uses_utc_timezone(self, client: TestClient) -> None:
        """Returned timestamp must be UTC-aware (offset +00:00 or Z)."""
        response = client.get("/api/health")
        ts_str = response.json()["timestamp"]
        parsed = datetime.datetime.fromisoformat(ts_str)
        # UTC offset must be zero.
        assert parsed.utcoffset() == datetime.timedelta(0), (
            f"Expected UTC (offset 0), got {parsed.utcoffset()}"
        )

    def test_timestamp_advances_between_calls(self, client: TestClient) -> None:
        """Successive calls should produce non-decreasing timestamps."""
        r1 = client.get("/api/health").json()["timestamp"]
        r2 = client.get("/api/health").json()["timestamp"]
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
            response = client.get("/api/health")

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
        for _ in range(5):
            response = client.get("/api/health")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "healthy"
            assert body["version"] == "1.0.0"
            _assert_utc_timestamp(body["timestamp"])

    def test_endpoint_registered_in_openapi_schema(self, client: TestClient) -> None:
        """The /api/health route must appear in the auto-generated OpenAPI spec."""
        schema = client.get("/openapi.json").json()
        paths = schema.get("paths", {})
        assert "/api/health" in paths, (
            f"/api/health not found in OpenAPI paths: {list(paths.keys())}"
        )

    def test_openapi_health_route_supports_get(self, client: TestClient) -> None:
        """The OpenAPI entry for /api/health must declare a GET operation."""
        schema = client.get("/openapi.json").json()
        health_ops = schema["paths"]["/api/health"]
        assert "get" in health_ops, (
            f"Expected 'get' operation for /api/health, found: {list(health_ops.keys())}"
        )

    def test_status_field_type_is_string(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert isinstance(body["status"], str)

    def test_version_field_type_is_string(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert isinstance(body["version"], str)

    def test_timestamp_field_type_is_string(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert isinstance(body["timestamp"], str)

    def test_version_semver_format(self, client: TestClient) -> None:
        """Version must follow MAJOR.MINOR.PATCH semver notation."""
        body = client.get("/api/health").json()
        semver_re = re.compile(r"^\d+\.\d+\.\d+$")
        assert semver_re.match(body["version"]), (
            f"Version {body['version']!r} does not match MAJOR.MINOR.PATCH"
        )
