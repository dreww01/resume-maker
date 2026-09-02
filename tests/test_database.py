import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from src.database import create_resume, get_resume, update_resume, delete_resume, get_engine_kwargs


def test_in_memory_sqlite_uses_static_pool():
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
    file_bytes = b"Sample resume binary content"
    filename = "test_resume.pdf"
    
    resume_id = create_resume(filename, file_bytes)
    assert isinstance(resume_id, int)
    assert resume_id > 0

    resume = get_resume(resume_id)
    assert resume is not None
    assert resume["id"] == resume_id
    assert resume["original_filename"] == filename
    assert resume["file_content"] == file_bytes
    assert resume["status"] == "uploaded"
    assert resume["created_at"] is not None
    assert resume["user_name"] is None
    assert resume["output_content"] is None
    assert resume["cover_letter_content"] is None


def test_get_nonexistent_resume():
    resume = get_resume(999999)
    assert resume is None


def test_update_resume():
    file_bytes = b"Original bytes"
    resume_id = create_resume("candidate.docx", file_bytes)

    updated = update_resume(
        resume_id,
        status="completed",
        user_name="John Doe",
        job_description="Senior Python Developer",
        output_content=b"Tailored DOCX bytes"
    )
    assert updated is True

    resume = get_resume(resume_id)
    assert resume["status"] == "completed"
    assert resume["user_name"] == "John Doe"
    assert resume["job_description"] == "Senior Python Developer"
    assert resume["output_content"] == b"Tailored DOCX bytes"


def test_update_nonexistent_resume():
    result = update_resume(999999, status="completed")
    assert result is False


def test_delete_resume():
    resume_id = create_resume("to_delete.pdf", b"data")
    assert get_resume(resume_id) is not None

    deleted = delete_resume(resume_id)
    assert deleted is True
    assert get_resume(resume_id) is None


def test_delete_nonexistent_resume():
    deleted = delete_resume(999999)
    assert deleted is False
