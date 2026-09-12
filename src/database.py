"""Database models, engine configuration, session management, and repository layer.

Provides deterministic session lifecycle management, robust SQLAlchemy error handling,
and typed CRUD functions using the Repository pattern.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import DateTime, Integer, LargeBinary, String, create_engine, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session as OrmSession, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from src.cache import cache, DEFAULT_CACHE_TTL, DASHBOARD_CACHE_TTL

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///:memory:")


def get_engine_kwargs(url: str) -> dict[str, Any]:
    """Build engine connection arguments customized per database backend.

    Args:
        url: SQLAlchemy connection string.

    Returns:
        Dictionary of keyword arguments for `create_engine`.
    """
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or "mode=memory" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
    return kwargs


engine_kwargs = get_engine_kwargs(DATABASE_URL)
engine = create_engine(DATABASE_URL, **engine_kwargs)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class Resume(Base):
    """SQLAlchemy model representing an uploaded and processed resume entity."""

    __tablename__ = "resume"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, default="uploaded", nullable=False)
    job_description: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    output_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True, default=None)
    cover_letter_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True, default=None)

    def __repr__(self) -> str:
        """Return a string representation of the Resume instance."""
        return f"<Resume(id={self.id}, name='{self.user_name}', original_filename='{self.original_filename}')>"

    def __getitem__(self, key: str) -> Any:
        """Provide dictionary-style attribute access for backward compatibility.

        Args:
            key: Name of the attribute to access.

        Returns:
            The attribute value.

        Raises:
            KeyError: If attribute does not exist.
        """
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Provide dictionary-style get method for backward compatibility.

        Args:
            key: Name of the attribute to access.
            default: Default value if attribute does not exist.

        Returns:
            The attribute value or default.
        """
        if hasattr(self, key):
            return getattr(self, key)
        return default

    @property
    def filename(self) -> str:
        """Alias for original_filename to support unified schema naming."""
        return self.original_filename

    @property
    def has_tailored_resume(self) -> bool:
        """Indicate whether output tailored resume content is present."""
        return self.output_content is not None

    @property
    def has_cover_letter(self) -> bool:
        """Indicate whether generated cover letter content is present."""
        return self.cover_letter_content is not None

    @property
    def has_output(self) -> bool:
        """Backward compatible alias for has_tailored_resume."""
        return self.output_content is not None


Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
# Retain Session alias for backward compatibility with existing usages
Session = SessionLocal


@contextmanager
def get_session() -> Generator[OrmSession, None, None]:
    """Provide a transactional database session scope with automatic rollback.

    Yields:
        Active SQLAlchemy ORM session.

    Raises:
        SQLAlchemyError: Propagates database exceptions after rolling back.
        Exception: Propagates non-database exceptions after rolling back.
    """
    session: OrmSession = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("Database error occurred during session execution: %s", exc, exc_info=True)
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_db() -> Generator[OrmSession, None, None]:
    """Context manager alias for get_session yielding a database session.

    Yields:
        Active SQLAlchemy ORM session.
    """
    with get_session() as session:
        yield session


class ResumeRepository:
    """Repository encapsulating persistence operations for Resume entities."""

    def __init__(self, session: Optional[OrmSession] = None) -> None:
        """Initialize repository with an optional explicit session.

        Args:
            session: Optional existing SQLAlchemy session to reuse.
        """
        self._session = session

    def create(self, filename: str, file_content: bytes) -> Resume:
        """Persist a new Resume entity from uploaded file data.

        Args:
            filename: Original file name (PDF or DOCX).
            file_content: Raw byte content of uploaded file.

        Returns:
            The created Resume model instance.

        Raises:
            SQLAlchemyError: If database persistence fails.
        """
        resume = Resume(
            original_filename=filename,
            file_content=file_content,
            status="uploaded",
        )
        if self._session is not None:
            self._session.add(resume)
            self._session.flush()
            cache.invalidate_by_tag("dashboard")
            cache.invalidate_by_tag("summary")
            return resume

        with get_session() as session:
            session.add(resume)
            session.flush()
            session.refresh(resume)
            cache.invalidate_by_tag("dashboard")
            cache.invalidate_by_tag("summary")
            return resume

    def get_by_id(self, resume_id: int) -> Optional[Resume]:
        """Fetch a resume record by its primary key.

        Args:
            resume_id: Primary key integer of the resume.

        Returns:
            Matching Resume model instance if found, or None.

        Raises:
            SQLAlchemyError: If database query encounters an error.
        """
        if self._session is not None:
            return self._session.query(Resume).filter(Resume.id == resume_id).first()

        cache_key = f"resume:{resume_id}"
        cached_resume = cache.get(cache_key)
        if cached_resume is not None:
            return cached_resume

        with get_session() as session:
            resume = session.query(Resume).filter(Resume.id == resume_id).first()
            if resume is not None:
                cache.set(cache_key, resume, ttl=DEFAULT_CACHE_TTL, tags={"resume", cache_key})
            return resume

    def update(self, resume_id: int, **fields: Any) -> Optional[Resume]:
        """Update fields of an existing resume record.

        Args:
            resume_id: Primary key integer of the resume to update.
            **fields: Arbitrary model attributes to assign.

        Returns:
            The updated Resume instance if found, or None if not found.

        Raises:
            SQLAlchemyError: If database update fails.
        """
        cache.delete(f"resume:{resume_id}")
        cache.invalidate_by_tag(f"resume:{resume_id}")
        cache.invalidate_by_tag("dashboard")
        cache.invalidate_by_tag("summary")

        if self._session is not None:
            resume = self._session.query(Resume).filter(Resume.id == resume_id).first()
            if not resume:
                return None
            for key, value in fields.items():
                if hasattr(resume, key):
                    setattr(resume, key, value)
            self._session.flush()
            return resume

        with get_session() as session:
            resume = session.query(Resume).filter(Resume.id == resume_id).first()
            if not resume:
                return None
            for key, value in fields.items():
                if hasattr(resume, key):
                    setattr(resume, key, value)
            session.flush()
            session.refresh(resume)
            return resume

    def delete(self, resume_id: int) -> bool:
        """Delete a resume record by its primary key.

        Args:
            resume_id: Primary key integer of the resume to delete.

        Returns:
            True if a record was found and deleted, False otherwise.

        Raises:
            SQLAlchemyError: If database deletion fails.
        """
        cache.delete(f"resume:{resume_id}")
        cache.invalidate_by_tag(f"resume:{resume_id}")
        cache.invalidate_by_tag("dashboard")
        cache.invalidate_by_tag("summary")

        if self._session is not None:
            resume = self._session.query(Resume).filter(Resume.id == resume_id).first()
            if not resume:
                return False
            self._session.delete(resume)
            self._session.flush()
            return True

        with get_session() as session:
            resume = session.query(Resume).filter(Resume.id == resume_id).first()
            if not resume:
                return False
            session.delete(resume)
            return True

    def get_dashboard_summary(self) -> dict[str, Any]:
        """Compute or retrieve cached dashboard summary metrics and recent activity feeds.

        Returns:
            Dictionary containing total_resumes, completed_count, pending_count,
            status_counts, and recent_activity.
        """
        cache_key = "dashboard:summary"
        cached_summary = cache.get(cache_key)
        if cached_summary is not None:
            return cached_summary

        def _calculate(session: OrmSession) -> dict[str, Any]:
            total_count = session.query(func.count(Resume.id)).scalar() or 0
            status_rows = (
                session.query(Resume.status, func.count(Resume.id))
                .group_by(Resume.status)
                .all()
            )
            status_counts = {str(st): count for st, count in status_rows}
            completed_count = status_counts.get("completed", 0)
            pending_count = status_counts.get("uploaded", 0) + status_counts.get("processing", 0)

            recent_rows = (
                session.query(Resume)
                .order_by(Resume.created_at.desc(), Resume.id.desc())
                .limit(10)
                .all()
            )
            recent_activity = [
                {
                    "id": r.id,
                    "filename": r.original_filename,
                    "status": r.status,
                    "user_name": r.user_name,
                    "created_at": r.created_at,
                }
                for r in recent_rows
            ]

            return {
                "total_resumes": total_count,
                "completed_count": completed_count,
                "pending_count": pending_count,
                "status_counts": status_counts,
                "recent_activity": recent_activity,
            }

        if self._session is not None:
            summary = _calculate(self._session)
        else:
            with get_session() as session:
                summary = _calculate(session)

        cache.set(cache_key, summary, ttl=DASHBOARD_CACHE_TTL, tags={"dashboard", "summary"})
        return summary

    def get_recent_activity(self, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent resume activity feed with caching.

        Args:
            limit: Maximum number of recent items to return.

        Returns:
            List of recent activity dictionaries.
        """
        cache_key = f"dashboard:recent_activity:{limit}"
        cached_feed = cache.get(cache_key)
        if cached_feed is not None:
            return cached_feed

        def _fetch(session: OrmSession) -> list[dict[str, Any]]:
            rows = (
                session.query(Resume)
                .order_by(Resume.created_at.desc(), Resume.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "filename": r.original_filename,
                    "status": r.status,
                    "user_name": r.user_name,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

        if self._session is not None:
            activity = _fetch(self._session)
        else:
            with get_session() as session:
                activity = _fetch(session)

        cache.set(cache_key, activity, ttl=DASHBOARD_CACHE_TTL, tags={"dashboard", "summary"})
        return activity


# Global default repository instance
_repo = ResumeRepository()


def create_resume(filename: str, file_content: bytes) -> int:
    """Create a new resume record and return its primary key ID.

    Args:
        filename: Name of the uploaded file.
        file_content: Raw bytes of the uploaded file.

    Returns:
        Integer identifier of the persisted resume.

    Raises:
        SQLAlchemyError: If database persistence fails.
    """
    resume = _repo.create(filename, file_content)
    return resume.id


def get_resume(resume_id: int) -> Optional[Resume]:
    """Retrieve resume record as a typed model instance (with backward compatible dict access).

    Args:
        resume_id: Unique primary key of the resume.

    Returns:
        Resume model instance, or None if no record matches.

    Raises:
        SQLAlchemyError: If query execution fails.
    """
    return _repo.get_by_id(resume_id)


def get_resume_model(resume_id: int) -> Optional[Resume]:
    """Retrieve resume entity as a typed SQLAlchemy model instance.

    Args:
        resume_id: Unique primary key of the resume.

    Returns:
        Resume model instance, or None if not found.

    Raises:
        SQLAlchemyError: If query execution fails.
    """
    return _repo.get_by_id(resume_id)


def update_resume(resume_id: int, **fields: Any) -> Optional[Resume]:
    """Update fields on a resume record.

    Args:
        resume_id: Unique primary key of the resume.
        **fields: Keyword arguments corresponding to model columns.

    Returns:
        Updated Resume model instance if found, or None if not found.

    Raises:
        SQLAlchemyError: If database update fails.
    """
    return _repo.update(resume_id, **fields)


def delete_resume(resume_id: int) -> bool:
    """Delete a resume record by ID.

    Args:
        resume_id: Unique primary key of the resume.

    Returns:
        True if deleted, False if record did not exist.

    Raises:
        SQLAlchemyError: If database deletion fails.
    """
    return _repo.delete(resume_id)


def get_dashboard_summary() -> dict[str, Any]:
    """Retrieve aggregated dashboard metrics and activity feed with caching.

    Returns:
        Dictionary of dashboard metrics.
    """
    return _repo.get_dashboard_summary()


def get_recent_activity(limit: int = 10) -> list[dict[str, Any]]:
    """Retrieve recent resume activity feed with caching.

    Args:
        limit: Number of recent items to fetch.

    Returns:
        List of recent activity item dicts.
    """
    return _repo.get_recent_activity(limit=limit)
