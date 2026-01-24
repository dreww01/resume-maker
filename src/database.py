import os
import logging
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import create_engine, Column, Integer, String, DateTime, LargeBinary
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///:memory:")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

Base = declarative_base()


class Resume(Base):
    __tablename__ = 'resume'
    id = Column(Integer, primary_key=True)
    original_filename = Column(String)
    file_content = Column(LargeBinary)
    user_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String)
    job_description = Column(String)
    output_content = Column(LargeBinary)
    cover_letter_content = Column(LargeBinary)

    def __repr__(self):
        return f"<Resume(name='{self.user_name}', original_filename='{self.original_filename}')>"


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


@contextmanager
def get_session():
    session = Session()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        session.close()


def create_resume(filename: str, file_content: bytes) -> int:
    with get_session() as session:
        resume = Resume(
            original_filename=filename,
            file_content=file_content,
            status='uploaded'
        )
        session.add(resume)
        session.flush()
        return resume.id


def get_resume(resume_id: int) -> dict | None:
    with get_session() as session:
        resume = session.query(Resume).filter(Resume.id == resume_id).first()
        if not resume:
            return None
        return {
            "id": resume.id,
            "original_filename": resume.original_filename,
            "file_content": resume.file_content,
            "user_name": resume.user_name,
            "created_at": resume.created_at,
            "status": resume.status,
            "job_description": resume.job_description,
            "output_content": resume.output_content,
            "cover_letter_content": resume.cover_letter_content
        }


def update_resume(resume_id: int, **fields) -> bool:
    with get_session() as session:
        resume = session.query(Resume).filter(Resume.id == resume_id).first()
        if not resume:
            return False
        for key, value in fields.items():
            if hasattr(resume, key):
                setattr(resume, key, value)
        return True


def delete_resume(resume_id: int) -> bool:
    with get_session() as session:
        resume = session.query(Resume).filter(Resume.id == resume_id).first()
        if not resume:
            return False
        session.delete(resume)
        return True
