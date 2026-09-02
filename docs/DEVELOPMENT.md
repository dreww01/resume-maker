# Local Development Guide

This guide walks you through setting up and working on **Resume Tailor** in your local development environment.

---

## 1. Prerequisites

Make sure you have the following installed on your machine:
- **Python 3.11 or 3.12+**
- **Git**
- An **OpenAI API Key** (or an alternative provider API key)

---

## 2. Environment Setup

### Option A: Using Standard Python Virtual Environment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/dreww01/resume-maker.git
   cd resume-maker
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv

   # On macOS / Linux:
   source .venv/bin/activate

   # On Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install pytest httpx
   ```

4. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```
   Open `.env` in your editor and add your `OPENAI_API_KEY`:
   ```env
   OPENAI_API_KEY=sk-proj-your-key-here
   AI_MODEL=gpt-4o-mini
   VISION_MODEL=gpt-4o-mini
   ```

---

### Option B: Using `uv` (Fastest)

1. **Install dependencies:**
   ```bash
   uv sync
   ```
2. **Activate the environment:**
   ```bash
   source .venv/bin/activate
   ```

---

## 3. Running the Application

Resume Tailor consists of two cooperating services:
1. **Backend API:** FastAPI running on port `8000`.
2. **Frontend UI:** Streamlit running on port `7860` (or `8501` by default).

### Running Services Separately (Recommended for Debugging)

**Terminal 1 — Backend:**
```bash
uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```
- API is accessible at: `http://localhost:8000`
- Interactive Swagger docs: `http://localhost:8000/docs`

**Terminal 2 — Frontend:**
```bash
streamlit run src/frontend.py
```
- Streamlit web interface opens in your browser at `http://localhost:8501`.

### Running with the Helper Script

You can start both services with a single command using `start.sh`:

```bash
chmod +x start.sh
./start.sh
```

---

## 4. Project Structure

```
resume-maker/
├── docs/                     # Comprehensive project documentation
│   ├── ARCHITECTURE.md       # High-level architecture & diagrams
│   ├── DATABASE.md           # Database schema & ERD
│   ├── API.md                # REST API reference & examples
│   ├── AI_MODELS.md          # AI prompt engineering & providers
│   ├── DEVELOPMENT.md        # Local development guide
│   └── DEPLOYMENT.md         # Docker & Hugging Face deployment
├── src/                      # Application source code
│   ├── __init__.py
│   ├── api.py                # FastAPI REST endpoints
│   ├── frontend.py           # Streamlit user interface
│   ├── database.py           # SQLAlchemy database layer
│   ├── resume_processor.py   # AI pipeline, OCR & DOCX generation
│   └── prompts/              # LLM prompt templates
│       ├── __init__.py
│       ├── resume_tailor.py  # Resume tailoring system/user prompts
│       └── cover_letter.py   # Cover letter prompt templates
├── tests/                    # Automated test suite
│   ├── test_database.py      # Database CRUD tests
│   ├── test_processor.py     # Document & prompt logic tests
│   └── test_api.py           # FastAPI endpoint tests
├── .github/                  # GitHub workflows & templates
│   ├── workflows/sync-to-hf.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── Dockerfile                # Production container specification
├── start.sh                  # Application startup script
├── pyproject.toml            # Project metadata & dependencies
├── requirements.txt          # Python package requirements
├── .env.example              # Sample environment configuration
├── CONTRIBUTING.md           # Contribution guidelines
├── CODE_OF_CONDUCT.md        # Community code of conduct
├── SECURITY.md               # Vulnerability reporting policy
├── CHANGELOG.md              # Release history
├── LICENSE                   # MIT License
└── README.md                 # Primary project readme
```

---

## 5. Running Automated Tests

Run the full test suite using `pytest`:

```bash
pytest
```

Run tests with verbose output and coverage:

```bash
pytest -v
```

Run a specific test file:

```bash
pytest tests/test_database.py
pytest tests/test_api.py
```

---

## 6. Coding Standards & Best Practices

- **Simplicity:** Write concise, readable code. Avoid over-engineering.
- **Type Annotations:** Use Python type hints on functions and methods.
- **Resource Management:** Ensure file descriptors, database sessions, and byte streams are properly closed using context managers (`with` statements).
- **Error Handling:** Always catch specific exceptions and return helpful error messages.
- **Tests First:** Write tests covering new endpoints, database queries, and parser functions.

---

## 7. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| `ValueError: OPENAI_API_KEY is not set` | Missing API key in `.env` | Ensure `.env` exists in root and contains `OPENAI_API_KEY=...`. |
| `Connection refused: 127.0.0.1:8000` | Backend API not running | Start the FastAPI server first using `uvicorn src.api:app --reload --port 8000`. |
| `ModuleNotFoundError: No module named 'src'` | Working directory mismatch | Run commands from the project root directory or set `export PYTHONPATH=.`. |
| `File must be .pdf or .docx` | Unsupported upload format | Upload only `.pdf` or `.docx` resume files. |
