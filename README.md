# Resume Tailor

A CLI tool that tailors your resume to specific job descriptions using AI, optimized for ATS (Applicant Tracking Systems).

## Features

- Reads resumes from PDF or DOCX files
- Uses OpenAI to tailor content to job descriptions
- Integrates relevant keywords from job postings
- Outputs a professionally formatted DOCX resume

## Requirements

- Python 3.x
- OpenAI API key

## Installation

```bash
pip install pypdf2 python-docx openai python-dotenv
```

## Setup

Create a `.env` file with your OpenAI API key:

```
OPENAI_API_KEY=your_key_here
```

## Usage

```bash
python resume.py
```

1. Place your resume as `olisa-resume.pdf` in the project directory
2. Run the script
3. Paste the job description when prompted
4. Type `END` on a new line when finished
5. Find your tailored resume in `tailored_resume.docx`

## Output

The tool generates an ATS-friendly DOCX with:
- Professional Summary
- Work Experience
- Key Projects
- Technical Skills
- Core Competencies
- Education
