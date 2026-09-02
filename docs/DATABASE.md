# Database Architecture & Schema

This document details the database layer, schema definition, and session management used in **Resume Tailor**.

---

## 1. Overview

Resume Tailor uses **SQLAlchemy ORM** to manage data persistence. By default, the application runs using an **in-memory SQLite database** (`sqlite:///:memory:`), which requires zero external configuration and cleans up automatically when the application stops.

For production deployments where persistence across restarts is needed, a persistent SQLite file or external relational database (such as PostgreSQL or MySQL) can be configured using the `DATABASE_URL` environment variable.

---

## 2. Entity-Relationship Diagram (ERD)

The database schema consists of the `resume` table, which stores both the raw uploaded resume files and the generated tailored documents.

```mermaid
erDiagram
    RESUME {
        integer id PK "Primary Key (Auto-Increment)"
        string original_filename "Original uploaded file name"
        blob file_content "Binary bytes of the uploaded file"
        string user_name "Candidate full name (extracted by AI)"
        datetime created_at "Timestamp of upload (UTC)"
        string status "Current status: uploaded | processing | completed"
        string job_description "Target job description text"
        blob output_content "Binary bytes of tailored DOCX resume"
        blob cover_letter_content "Binary bytes of generated DOCX cover letter"
    }
```

---

## 3. Table Schema: `resume`

| Column Name | Data Type | Nullable | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | No | Auto-increment | Unique identifier for each resume record. |
| `original_filename` | `VARCHAR` | Yes | `NULL` | The original file name uploaded by the user (e.g. `resume.pdf`). |
| `file_content` | `BLOB` (`LargeBinary`) | Yes | `NULL` | Binary content of the original uploaded PDF or DOCX file. |
| `user_name` | `VARCHAR` | Yes | `NULL` | The candidate's name parsed by the AI model during tailoring. |
| `created_at` | `DATETIME(timezone=True)` | Yes | `lambda: datetime.now(timezone.utc)` | Timestamp when the resume record was created (UTC with timezone). |
| `status` | `VARCHAR` | Yes | `'uploaded'` | Lifecycle state: `'uploaded'`, `'processing'`, or `'completed'`. |
| `job_description` | `TEXT` (`String`) | Yes | `NULL` | The text of the target job description submitted by the user. |
| `output_content` | `BLOB` (`LargeBinary`) | Yes | `NULL` | Binary content of the generated tailored DOCX resume. |
| `cover_letter_content` | `BLOB` (`LargeBinary`) | Yes | `NULL` | Binary content of the generated DOCX cover letter. |

---

## 4. Lifecycle States

```mermaid
stateDiagram-v2
    [*] --> uploaded : User uploads PDF/DOCX (POST /upload)
    uploaded --> processing : User starts tailoring (POST /resumes/{id}/tailor)
    processing --> completed : AI processing & DOCX generation succeed
    completed --> [*] : User downloads file (GET /resumes/{id}/download)
```

- **`uploaded`:** File is received and stored in the database. Ready for tailoring or cover letter generation.
- **`processing`:** AI model is actively extracting text and formatting the tailored resume.
- **`completed`:** Tailored resume binary has been generated and stored in `output_content`, ready for download.

---

## 5. Database Connection & Session Management

The database layer (`src/database.py`) uses a context manager to ensure safe session handling, automatic commits, and rollback on error:

```python
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
```

### Core Database Operations

1. **`create_resume(filename: str, file_content: bytes) -> int`**
   - Inserts a new resume row with initial status `uploaded`.
   - Returns the generated `resume.id`.

2. **`get_resume(resume_id: int) -> dict | None`**
   - Fetches a resume by primary key ID and returns its fields as a Python dictionary.
   - Returns `None` if the resume ID does not exist.

3. **`update_resume(resume_id: int, **fields) -> bool`**
   - Updates one or more fields (e.g. `status`, `output_content`, `user_name`, `job_description`) for a given resume ID.
   - Returns `True` if the record was found and updated, `False` otherwise.

4. **`delete_resume(resume_id: int) -> bool`**
   - Deletes the resume record associated with the given ID.
   - Returns `True` if deleted, `False` if not found.

---

## 6. Configuration Options

Set the database connection string via the `DATABASE_URL` environment variable in your `.env` file:

### SQLite In-Memory (Default)
```env
DATABASE_URL=sqlite:///:memory:
```
*Best for local testing and ephemeral cloud deployments like Hugging Face Spaces.*

### SQLite File Persistence
```env
DATABASE_URL=sqlite:///./resume.db
```
*Best for persistent local runs or small-scale self-hosted servers.*

### PostgreSQL
```env
DATABASE_URL=postgresql://user:password@localhost:5432/resume_db
```
*Best for scalable multi-user production environments.*
