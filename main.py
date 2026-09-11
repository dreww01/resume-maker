"""Root application entrypoint alias.

Provides root-level application exposure (``from main import app``)
for compatibility with standard ASGI runners and test suites.
"""

from src.api import app

__all__ = ["app"]
