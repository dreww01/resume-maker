# Contributing to Resume Maker

Thank you for contributing to Resume Maker! This document provides guidelines, conventions, and architectural context to help you get started with development.

---

## Table of Contents

1. [Architecture Quick-Reference](#architecture-quick-reference)
   - [System Components](#system-components)
   - [Data Flow](#data-flow)
2. [Development Setup](#development-setup)
3. [Branch Naming Convention](#branch-naming-convention)
4. [Commit Conventions](#commit-conventions)
5. [Testing and Quality Assurance](#testing-and-quality-assurance)
6. [Submitting a Pull Request](#submitting-a-pull-request)

---

## Architecture Quick-Reference

Resume Maker is designed as a modular AI-powered resume tailoring and cover letter generation application consisting of the following primary components:

### System Components

```
resume-maker/
├── src/
│   ├── api.py              # FastAPI REST API endpoints
│   ├── frontend.py         # Streamlit interactive web interface
│   ├── resume_processor.py # PDF/DOCX parsing, OpenAI API orchestration, DOCX generation
│   ├── database.py         # SQLAlchemy ORM models & session management
│   └── prompts/            # LLM prompt templates
│       ├── resume_tailor.py  # Structured prompt for ATS optimization
│       └── cover_letter.py   # Structured prompt for cover letter creation
```

- **Frontend (`src/frontend.py`)**: Built with Streamlit, providing an interactive UI for users to upload resumes, input target job descriptions, view processing progress, and download output documents.
- **Backend API (`src/api.py`)**: FastAPI application providing RESTful endpoints (`/upload`, `/resumes/{id}/tailor`, `/resumes/{id}/cover-letter`, `/resumes/{id}/download`, etc.).
- **Processing Engine (`src/resume_processor.py`)**: Extracts text from PDF (`pypdf2`, `pypdfium2`) and DOCX (`python-docx`), queries the configured LLM provider (OpenAI SDK compatible), and reconstructs styled Word documents (`.docx`).
- **Database Layer (`src/database.py`)**: SQLAlchemy ORM for managing resume metadata, document binaries, job descriptions, and processing states. Defaults to in-memory SQLite (`sqlite:///:memory:`) or persistent database configured via `DATABASE_URL`.
- **Prompts (`src/prompts/`)**: Structured prompt definitions ensuring ATS-friendly keyword alignment, standard section formatting, and customized tone.

### Data Flow

1. **Upload**: User uploads `.pdf` or `.docx` resume via Frontend or REST API (`POST /upload`). The file content is stored in the database.
2. **Analysis & Tailoring**: User submits job description (`POST /resumes/{id}/tailor`). The backend reads raw resume text, sends it alongside the job description to the LLM, and parses structured output.
3. **Document Generation**: The tailored output is rendered into a formatted `.docx` file using `python-docx` and saved to the database.
4. **Download**: The user downloads the resulting ATS-tailored resume or generated cover letter (`GET /resumes/{id}/download`).

---

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/dreww01/resume-maker.git
   cd resume-maker
   ```

2. **Set up Environment**:
   Using `uv` (recommended):
   ```bash
   uv venv
   uv sync
   ```
   Or using standard `venv` & `pip`:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   # Edit .env and supply your OPENAI_API_KEY
   ```

---

## Branch Naming Convention

When creating a new feature, fix, or task branch, follow the project branch naming convention:

- **Format**: `dsh/<issue-id>`
- **Examples**:
  - `dsh/ORC-6`
  - `dsh/ORC-42`
  - `dsh/issue-123`

---

## Commit Conventions

We adhere to the [Conventional Commits](https://www.conventionalcommits.org/) standard. Commit messages should follow this structure:

```
<type>(<optional-scope>): <description>

[optional body]

[optional footer(s)]
```

### Commit Types

- `feat`: A new feature or capability
- `fix`: A bug fix
- `docs`: Documentation changes only
- `test`: Adding or correcting unit/integration tests
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: A code change that improves performance
- `chore`: Changes to build process, auxiliary tools, or libraries

### Examples

- `feat(api): add endpoint for batch resume processing`
- `fix(processor): resolve encoding error in docx parser`
- `docs(readme): add contributing and architecture reference`
- `test(database): add unit test for resume record creation`

---

## Testing and Quality Assurance

Before submitting any changes, verify that all test suites pass and adhere to code health standards.

### Running Tests

Execute the test suite using `uv`:
```bash
uv run pytest -v
```

Or using standard `pytest`:
```bash
pytest -v
```

### Code Health Standards

- Follow [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
- Keep functions modular, well-typed, and documented.
- Ensure all relative and absolute markdown links resolve properly.
- Do not modify backend API routes or runner code without explicit task authorization.

---

## Submitting a Pull Request

1. Ensure your branch follows `dsh/<issue-id>`.
2. Run the test suite: `uv run pytest -v`.
3. Commit your changes following Conventional Commits.
4. Push your branch to GitHub:
   ```bash
   git push origin dsh/<issue-id>
   ```
5. Open a Pull Request against the `master` branch with a clear description of the changes made and link the relevant issue.
