# Architecture Overview

This document describes the system architecture, component design, and data flow of **Resume Tailor**.

---

## 1. High-Level System Architecture

Resume Tailor is built with a decoupled architecture featuring a **Streamlit** user interface, a **FastAPI** backend server, a **SQLAlchemy** database storage layer, and an **AI processing engine** integrating multimodal and chat models.

```mermaid
flowchart TD
    User([👤 User / Browser])

    subgraph Frontend [Presentation Layer]
        UI[Streamlit Web App\nsrc/frontend.py\nPort: 8501]
    end

    subgraph Backend [Application Layer]
        API[FastAPI Server\nsrc/api.py\nPort: 8000]
        Processor[Resume Processor\nsrc/resume_processor.py]
        Prompts[Prompt Templates\nsrc/prompts/]
    end

    subgraph Storage [Data Layer]
        DB[(SQLAlchemy / SQLite\nsrc/database.py)]
    end

    subgraph External [AI & Document Services]
        VisionAI[OpenAI Vision Model\nPDF Text Extraction]
        ChatAI[OpenAI Chat Model\nResume & Cover Letter Tailoring]
        DocxGen[python-docx Engine\nDOCX File Builder]
    end

    User <-->|HTTP / UI Interaction| UI
    UI <-->|REST API Calls| API
    API <-->|Read / Write Resumes| DB
    API -->|Process Requests| Processor
    Processor -->|Load Prompts| Prompts
    Processor -->|Extract PDF Images| VisionAI
    Processor -->|Generate Tailored Content| ChatAI
    Processor -->|Compile Formatted Doc| DocxGen
    DocxGen -->|DOCX Bytes| API
```

---

## 2. End-to-End Workflow & Sequence Diagram

The complete user workflow consists of three primary phases: **Upload**, **Tailor / Generate**, and **Download**.

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant UI as Streamlit UI
    participant API as FastAPI Backend
    participant DB as SQLite Database
    participant AI as OpenAI API
    participant Docx as python-docx

    %% Phase 1: Upload
    Note over User,DB: Phase 1: Resume Upload
    User->>UI: Upload resume (PDF or DOCX)
    UI->>API: POST /upload (multipart file)
    API->>DB: create_resume(filename, file_bytes)
    DB-->>API: resume_id
    API-->>UI: { id: resume_id, filename: string }
    UI-->>User: Show uploaded status & ID

    %% Phase 2: Tailoring
    Note over User,Docx: Phase 2: Resume Tailoring & Generation
    User->>UI: Paste job description & click "Tailor Resume"
    UI->>API: POST /resumes/{id}/tailor (text/plain job description)
    API->>DB: update_status("processing")
    API->>API: read_resume() (extract text via Vision / python-docx)
    opt PDF file input
        API->>AI: Send page images to Vision Model
        AI-->>API: Extracted raw text
    end
    API->>AI: Send raw resume + job description + JSON prompt
    AI-->>API: Structured JSON (tailored content)
    API->>Docx: create_docx(tailored_data)
    Docx-->>API: Generated DOCX binary bytes
    API->>DB: update_resume(status="completed", output_content=bytes, user_name=name)
    API-->>UI: { status: "completed", user_name: name }
    UI-->>User: Display success message

    %% Phase 3: Download
    Note over User,API: Phase 3: Download Tailored Document
    User->>UI: Click "Download Tailored Resume"
    UI->>API: GET /resumes/{id}/download
    API->>DB: get_resume(id)
    DB-->>API: resume record with output_content
    API-->>UI: Binary DOCX stream with attachment filename
    UI-->>User: File download prompt
```

---

## 3. Core Components

### 3.1 Presentation Layer (`src/frontend.py`)
- **Technology:** Streamlit
- **Responsibilities:**
  - Provides a clean, responsive single-page web interface.
  - Handles file uploads (`.pdf`, `.docx`).
  - Accepts target job description input.
  - Triggers asynchronous API calls to the backend.
  - Manages UI session state (`resume_id`, `status`).
  - Provides one-click file download buttons for generated resumes and cover letters.

### 3.2 Application Layer (`src/api.py`)
- **Technology:** FastAPI, Uvicorn
- **Responsibilities:**
  - Exposes RESTful endpoints for resume management.
  - Implements CORS middleware for cross-origin integration.
  - Validates incoming file formats and payload bodies.
  - Coordinates database queries and processing jobs.
  - Streams binary `.docx` downloads with proper HTTP headers (`Content-Disposition`).

### 3.3 Business Logic & Processing (`src/resume_processor.py`)
- **Technology:** OpenAI SDK, `pypdfium2`, `python-docx`, Pillow
- **Responsibilities:**
  - **PDF Text Extraction:** Converts PDF pages to high-resolution PNG images via `pypdfium2` and passes them to a vision model (`gpt-4o-mini`) for structure-preserving OCR.
  - **DOCX Text Extraction:** Reads native `.docx` paragraphs using `python-docx`.
  - **Resume Tailoring:** Formulates structured system and user prompts to rewrite resume bullet points, summaries, and skills to align with the job description.
  - **Cover Letter Generation:** Synthesizes candidate background and job requirements into a compelling, professional cover letter.
  - **DOCX Generation:** Dynamically formats and compiles professional `.docx` files with custom typography, clean spacing, and section headers.

### 3.4 Prompt Templates (`src/prompts/`)
- **`resume_tailor.py`:** Contains system instructions and JSON response schema guidelines enforcing ATS keyword optimization, active verb usage, and realistic alignment.
- **`cover_letter.py`:** Contains prompts guiding the AI to write concise, impact-focused cover letters tailored to the target role.

### 3.5 Data Persistence Layer (`src/database.py`)
- **Technology:** SQLAlchemy ORM, SQLite
- **Responsibilities:**
  - Defines the `Resume` data model.
  - Provides a thread-safe session context manager (`get_session()`).
  - Stores uploaded source files, processing status, job descriptions, and generated output binaries.

---

## 4. Document Ingestion & Processing Pipeline

The ingestion pipeline handles both structured DOCX files and visually formatted PDFs:

```mermaid
flowchart LR
    Input[Upload File] --> TypeCheck{File Type?}

    TypeCheck -->|PDF| PDFEngine[pypdfium2 Render Engine]
    PDFEngine --> ImgBuffer[In-Memory PNG Images]
    ImgBuffer --> VisionModel[Vision LLM OCR]
    VisionModel --> ExtractedText[Extracted Plain Text]

    TypeCheck -->|DOCX| DocxReader[python-docx Parser]
    DocxReader --> ExtractedText

    ExtractedText --> AIPipeline[AI Tailoring Engine]
    JobDesc[Job Description] --> AIPipeline

    AIPipeline --> JSONData[Structured JSON Output]
    JSONData --> DocxBuilder[python-docx Builder]
    DocxBuilder --> FinalDOCX[Tailored DOCX Document]
```

---

## 5. Security & Isolation

- **In-Memory Defaults:** The default database runs in SQLite in-memory mode, ensuring no files persist on disk unless explicitly configured with `DATABASE_URL`.
- **Stateless Processing:** Uploaded files and temporary images generated during PDF OCR are immediately unlinked and removed from disk after processing.
- **Environment Isolation:** API keys and sensitive settings are strictly read from environment variables and never exposed to the client.
