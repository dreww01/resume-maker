"""Test configuration and fixtures."""

import os

# Set dummy environment variables before importing app modules
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
