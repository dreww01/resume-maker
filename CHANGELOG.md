# Changelog

All notable changes to the **Resume Tailor** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Comprehensive project documentation suite under `docs/`:
  - `docs/ARCHITECTURE.md`: High-level system architecture and sequence diagrams.
  - `docs/DATABASE.md`: Database schema, ER diagrams, and SQLAlchemy session management.
  - `docs/API.md`: Complete FastAPI endpoint reference with request/response schemas.
  - `docs/AI_MODELS.md`: Multi-provider configuration guide (OpenAI, Gemini, Groq, Ollama).
  - `docs/DEVELOPMENT.md`: Local development guide, testing, and contribution standards.
  - `docs/DEPLOYMENT.md`: Docker and Hugging Face Spaces deployment guide.
- Standard open source documentation files:
  - `CONTRIBUTING.md`
  - `CODE_OF_CONDUCT.md`
  - `SECURITY.md`
  - `LICENSE`
  - GitHub issue and pull request templates (`.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`).
- Automated unit and integration test suite covering database operations, processor utilities, and API endpoints.

---

## [0.1.0] - 2025-01-15

### Added
- **Core AI Resume Tailoring:** Automatic resume rewriting aligned to job descriptions and target keywords.
- **Cover Letter Generation:** Personalized cover letter creation based on extracted candidate background.
- **Multimodal PDF Parsing:** PDF text extraction powered by `pypdfium2` and vision AI models.
- **DOCX Parsing & Export:** Support for parsing `.docx` input and exporting clean, professionally formatted `.docx` resumes and cover letters.
- **FastAPI Backend:** Asynchronous REST API managing file uploads, processing workflows, and downloads.
- **Streamlit Frontend:** Clean web interface for resume upload, job description input, and one-click downloads.
- **Database Layer:** SQLAlchemy ORM integration supporting in-memory and persistent SQLite configurations.
- **Docker & Cloud Support:** Docker container configuration and Hugging Face Spaces deployment integration.
