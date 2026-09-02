import os
import pytest
from sqlalchemy.pool import StaticPool
from src.database import create_database_engine, create_resume, get_resume, update_resume, delete_resume


def test_in_memory_sqlite_uses_static_pool():
    """In-memory SQLite database URLs should use StaticPool."""
    engine = create_database_engine("sqlite:///:memory:")
    assert isinstance(engine.pool, StaticPool)

    engine_shorthand = create_database_engine("sqlite://")
    assert isinstance(engine_shorthand.pool, StaticPool)


def test_file_based_sqlite_does_not_use_static_pool():
    """File-based SQLite database URLs should not use StaticPool."""
    engine = create_database_engine("sqlite:///app.db")
    assert not isinstance(engine.pool, StaticPool)

    engine_abs = create_database_engine("sqlite:////tmp/test.db")
    assert not isinstance(engine_abs.pool, StaticPool)


def test_database_crud_operations():
    """Verify basic CRUD operations work with database helper functions."""
    resume_id = create_resume("test_db.pdf", b"%PDF-1.4 test")
    assert resume_id is not None

    fetched = get_resume(resume_id)
    assert fetched is not None
    assert fetched["original_filename"] == "test_db.pdf"
    assert fetched["status"] == "uploaded"

    updated = update_resume(resume_id, user_name="Alice Smith", status="completed")
    assert updated is True

    fetched_updated = get_resume(resume_id)
    assert fetched_updated["user_name"] == "Alice Smith"
    assert fetched_updated["status"] == "completed"

    deleted = delete_resume(resume_id)
    assert deleted is True
    assert get_resume(resume_id) is None
