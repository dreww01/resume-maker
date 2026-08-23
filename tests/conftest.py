import os

# Test isolation guarantees: these MUST be set before any `src` module import,
# because src.resume_processor raises at import time when OPENAI_API_KEY is
# missing, and src.database binds its SQLAlchemy engine to DATABASE_URL at
# import time. setdefault keeps explicit overrides working while ensuring the
# suite never touches a real database or requires real credentials.
os.environ.setdefault("OPENAI_API_KEY", "test-mock-api-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
