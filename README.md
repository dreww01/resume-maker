# Resume Tailor

AI-powered resume tailoring and cover letter generation tool. Upload your resume, paste a job description, and get an ATS-optimized resume tailored to the specific role.

## Features

- **Resume Tailoring**: Automatically rewrites your resume to match job description keywords
- **Cover Letter Generation**: Creates personalized cover letters based on your experience
- **ATS Optimization**: Ensures your resume passes Applicant Tracking Systems
- **Multiple Formats**: Supports PDF and DOCX input
- **Modern Output**: Generates clean, professional DOCX files

## Prerequisites

- Python 3.11+
- OpenAI API key

## Installation

1. Clone the repository:

```bash
git clone https://github.com/dreww01/resume-maker.git
cd resume-maker
```

2. Create and activate virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set up environment variables:

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | Your OpenAI API key |
| `AI_MODEL` | No | `gpt-4o-mini` | Model for resume tailoring and cover letters |
| `VISION_MODEL` | No | `gpt-4o-mini` | Model for PDF text extraction |
| `DATABASE_URL` | No | `sqlite:///:memory:` | Database connection string |

### Using Alternative Models (Free Options)

You can use free or cheaper models by changing the provider. The app uses the OpenAI SDK which is compatible with many providers.

**Google Gemini (Free tier available):**
```bash
OPENAI_API_KEY=your-google-api-key
AI_MODEL=gemini-2.0-flash
VISION_MODEL=gemini-2.0-flash
```
Note: Requires modifying `resume_processor.py` to use Gemini's base URL.

**Groq (Free tier: 14,400 requests/day):**
```bash
OPENAI_API_KEY=your-groq-api-key
AI_MODEL=llama-3.1-70b-versatile
VISION_MODEL=llama-3.2-90b-vision-preview
```
Note: Requires modifying `resume_processor.py` to use `base_url="https://api.groq.com/openai/v1"`.

**Local with Ollama (Completely free):**
```bash
OPENAI_API_KEY=ollama
AI_MODEL=llama3.1
VISION_MODEL=llava
```
Note: Requires Ollama running locally and modifying `resume_processor.py` to use `base_url="http://localhost:11434/v1"`.

## Usage

### Local Development

Start the API server:

```bash
uvicorn src.api:app --reload --port 8000
```

In a separate terminal, start the Streamlit frontend:

```bash
streamlit run src/frontend.py
```

Or run both with the startup script:

```bash
./start.sh
```

### API Endpoints

| Endpoint                              | Method | Description                      |
| ------------------------------------- | ------ | -------------------------------- |
| `/upload`                             | POST   | Upload a resume (PDF/DOCX)       |
| `/resumes/{id}/tailor`                | POST   | Tailor resume to job description |
| `/resumes/{id}/cover-letter`          | POST   | Generate cover letter            |
| `/resumes/{id}/download`              | GET    | Download tailored resume         |
| `/resumes/{id}/cover-letter/download` | GET    | Download cover letter            |

### API Documentation

Once running, visit `http://localhost:8000/docs` for interactive API documentation.

## Project Structure

```
resume-tailor/
├── src/
│   ├── __init__.py
│   ├── api.py              # FastAPI backend
│   ├── frontend.py         # Streamlit UI
│   ├── resume_processor.py # Core processing logic
│   ├── database.py         # Database layer
│   └── prompts/
│       ├── __init__.py
│       ├── resume_tailor.py
│       └── cover_letter.py
├── start.sh                # Startup script
├── Dockerfile              # Container config
├── requirements.txt
├── .env.example
└── README.md
```

## Hugging Face Spaces Deployment

This project is configured for Hugging Face Spaces:

1. Create a new Space with Docker SDK
2. Add `OPENAI_API_KEY` to Space secrets
3. Push this repository to the Space

The app will be available on port 7860.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "feat: add your feature"`
4. Push to branch: `git push origin feature/your-feature`
5. Open a Pull Request

## License

MIT
