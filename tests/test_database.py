"""Unit tests for SQLAlchemy database models and repository layer operations."""

from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import StaticPool
from src.database import (
    Resume,
    ResumeRepository,
    create_resume,
    delete_resume,
    get_db,
    get_engine_kwargs,
    get_resume,
    get_resume_model,
    get_session,
    update_resume,
)


def test_in_memory_sqlite_uses_static_pool():
    """Verify in-memory SQLite connection strings configure StaticPool correctly."""
    in_memory_urls = [
        "sqlite:///:memory:",
        "sqlite://",
        "sqlite:///",
        "sqlite:///file:memdb1?mode=memory&cache=shared",
    ]
    for url in in_memory_urls:
        kwargs = get_engine_kwargs(url)
        assert kwargs.get("poolclass") == StaticPool
        engine = create_engine(url, **kwargs)
        assert isinstance(engine.pool, StaticPool)


def test_file_based_sqlite_does_not_use_static_pool():
    """Verify file-backed SQLite connections do not use StaticPool."""
    file_urls = [
        "sqlite:///test.db",
        "sqlite:////tmp/test.db",
    ]
    for url in file_urls:
        kwargs = get_engine_kwargs(url)
        assert kwargs.get("poolclass") != StaticPool
        engine = create_engine(url, **kwargs)
        assert not isinstance(engine.pool, StaticPool)


def test_create_and_get_resume():
    """Verify creating and retrieving resume via dict and model access."""
    file_bytes = b"Sample resume binary content"
    filename = "test_resume.pdf"

    resume_id = create_resume(filename, file_bytes)
    assert isinstance(resume_id, int)
    assert resume_id > 0

    resume = get_resume(resume_id)
    assert resume is not None
    assert resume["id"] == resume_id
    assert resume["original_filename"] == filename
    assert resume["filename"] == filename
    assert resume["file_content"] == file_bytes
    assert resume["status"] == "uploaded"
    assert resume["created_at"] is not None
    assert resume["user_name"] is None
    assert resume["output_content"] is None
    assert resume["cover_letter_content"] is None
    assert resume["has_tailored_resume"] is False
    assert resume["has_cover_letter"] is False

    # Also test get_resume_model
    model = get_resume_model(resume_id)
    assert model is not None
    assert model.id == resume_id
    assert model.original_filename == filename
    assert model.has_tailored_resume is False
    assert model.has_cover_letter is False


def test_get_nonexistent_resume():
    """Verify querying invalid ID returns None."""
    resume = get_resume(999999)
    assert resume is None

    model = get_resume_model(999999)
    assert model is None


def test_update_resume():
    """Verify updating fields on an existing resume record."""
    file_bytes = b"Original bytes"
    resume_id = create_resume("candidate.docx", file_bytes)

    updated_model = update_resume(
        resume_id,
        status="completed",
        user_name="John Doe",
        job_description="Senior Python Developer",
        output_content=b"Tailored DOCX bytes",
    )
    assert updated_model is not None
    assert updated_model.status == "completed"
    assert updated_model.user_name == "John Doe"

    resume = get_resume(resume_id)
    assert resume is not None
    assert resume["status"] == "completed"
    assert resume["user_name"] == "John Doe"
    assert resume["job_description"] == "Senior Python Developer"
    assert resume["output_content"] == b"Tailored DOCX bytes"
    assert resume["has_tailored_resume"] is True


def test_update_nonexistent_resume():
    """Verify updating nonexistent resume returns None."""
    result = update_resume(999999, status="completed")
    assert result is None


def test_delete_resume():
    """Verify deleting a resume returns True and removes it from the database."""
    resume_id = create_resume("to_delete.pdf", b"data")
    assert get_resume(resume_id) is not None

    deleted = delete_resume(resume_id)
    assert deleted is True
    assert get_resume(resume_id) is None


def test_delete_nonexistent_resume():
    """Verify deleting nonexistent record returns False."""
    deleted = delete_resume(999999)
    assert deleted is False


def test_repository_with_explicit_session():
    """Verify ResumeRepository operations when reusing a provided session."""
    with get_db() as session:
        repo = ResumeRepository(session=session)
        created = repo.create("repo_test.docx", b"test content")
        assert created.id > 0

        found = repo.get_by_id(created.id)
        assert found is not None
        assert found.original_filename == "repo_test.docx"

        updated = repo.update(created.id, status="processing")
        assert updated is not None
        assert updated.status == "processing"

        deleted = repo.delete(created.id)
        assert deleted is True
        assert repo.get_by_id(created.id) is None


def test_get_session_rollback_on_sqlalchemy_error():
    """Verify session rollback occurs when SQLAlchemyError is raised."""
    with patch.object(OrmSession, "rollback") as mock_rollback:
        with pytest.raises(SQLAlchemyError):
            with get_session():
                raise SQLAlchemyError("Simulated database failure")
        mock_rollback.assert_called_once()


def test_get_session_rollback_on_non_sqlalchemy_exception():
    """Verify session rollback occurs when a non-SQLAlchemy exception (e.g. ValueError) is raised."""
    with patch.object(OrmSession, "rollback") as mock_rollback:
        with pytest.raises(ValueError, match="Non-database application exception"):
            with get_session() as session:
                resume = Resume(original_filename="rollback_test.pdf", file_content=b"test")
                session.add(resume)
                raise ValueError("Non-database application exception")
        mock_rollback.assert_called_once()


def test_get_session_rollback_state_verification():
    """Verify uncommitted database state is discarded on non-database exception."""
    filename = "should_not_exist.pdf"
    with pytest.raises(RuntimeError):
        with get_session() as session:
            resume = Resume(original_filename=filename, file_content=b"test data")
            session.add(resume)
            session.flush()
            created_id = resume.id
            raise RuntimeError("Operation aborted")

    with get_session() as session:
        repo = ResumeRepository(session=session)
        assert repo.get_by_id(created_id) is None
