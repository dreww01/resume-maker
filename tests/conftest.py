"""Test configuration and global fixtures for pytest."""

import sys
from types import ModuleType
from unittest import mock

import pytest


def _make_module_stub(name: str, **attrs) -> ModuleType:
    """Return a minimal module stub with permissive attribute access.

    Any attribute not explicitly provided via *attrs* is a fresh MagicMock,
    so ``from stub_module import anything`` always succeeds.
    """
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


@pytest.fixture(scope="session", autouse=True)
def _stub_heavy_deps():
    """Stub out heavy or external dependencies for the duration of the test session.

    Restores original sys.modules entries during teardown to avoid cross-test
    isolation issues.
    """
    pm_version = "0.0.20"
    pm_multipart_stub = _make_module_stub(
        "python_multipart.multipart",
        parse_options_header=mock.MagicMock(),
    )
    pm_stub = _make_module_stub(
        "python_multipart",
        __version__=pm_version,
        multipart=pm_multipart_stub,
    )

    stubs = {
        "python_multipart": pm_stub,
        "python_multipart.multipart": pm_multipart_stub,
        "multipart": _make_module_stub("multipart", __version__=pm_version),
        "multipart.multipart": _make_module_stub(
            "multipart.multipart",
            parse_options_header=mock.MagicMock(),
        ),
        "src.database": _make_module_stub("src.database"),
        "src.resume_processor": _make_module_stub("src.resume_processor"),
    }

    originals = {}
    for name, stub in stubs.items():
        originals[name] = sys.modules.get(name)
        sys.modules[name] = stub

    yield

    for name, original in originals.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
