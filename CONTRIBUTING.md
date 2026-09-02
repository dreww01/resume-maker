# Contributing to Resume Tailor

Thank you for your interest in contributing to Resume Tailor! We welcome all contributions, including bug reports, feature requests, documentation improvements, and code changes.

Please read this guide to learn how you can contribute effectively.

---

## Code of Conduct

All contributors and participants are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md). Please be respectful, welcoming, and constructive in all interactions.

---

## How Can I Contribute?

You can contribute in several ways:
- **Report bugs:** Open an issue if you find a bug or unexpected behavior.
- **Suggest features:** Share your ideas for new features or improvements.
- **Improve documentation:** Fix typos, clarify instructions, or add examples.
- **Submit code:** Fix bugs or implement new features via Pull Requests.

---

## Getting Started

### 1. Fork and Clone the Repository

1. Fork the repository on GitHub.
2. Clone your fork locally:

```bash
git clone https://github.com/<your-username>/resume-maker.git
cd resume-maker
```

### 2. Set Up a Virtual Environment

Create and activate a Python virtual environment (Python 3.11+ recommended):

```bash
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### 3. Install Dependencies

Install project dependencies and development tools:

```bash
pip install -r requirements.txt
pip install pytest httpx
```

Or using `uv`:

```bash
uv sync
```

### 4. Configure Environment Variables

Copy the example environment file and set your OpenAI API key:

```bash
cp .env.example .env
```

Edit `.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here
AI_MODEL=gpt-4o-mini
VISION_MODEL=gpt-4o-mini
```

---

## Development Workflow

### 1. Create a Branch

Always create a new branch from `master` for your changes:

```bash
git checkout -b feat/my-new-feature
# or for bug fixes:
git checkout -b fix/issue-description
```

Use descriptive branch names:
- `feat/feature-name` for new features
- `fix/bug-name` for bug fixes
- `docs/doc-update` for documentation changes
- `refactor/cleanup` for code refactoring

### 2. Run the Application Locally

Start the backend API server:

```bash
uvicorn src.api:app --reload --port 8000
```

In a second terminal, start the Streamlit UI:

```bash
streamlit run src/frontend.py
```

You can also use the startup script:

```bash
./start.sh
```

### 3. Run Automated Tests

Run the test suite to ensure everything works properly:

```bash
pytest
```

Make sure all tests pass before committing your changes.

---

## Code Style and Guidelines

- **Python Version:** Python 3.11 or higher.
- **Formatting & Linting:** Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- **Type Hints:** Add type annotations where appropriate.
- **Simplicity:** Keep code clean, readable, and simple. Avoid unnecessary complexity.
- **Comments:** Write comments that explain *why* something is done, not just *what*.
- **Tests:** Add unit tests for any new endpoints, database functions, or processor logic.

---

## Pull Request Guidelines

1. **Keep it focused:** Each Pull Request should address one issue or feature.
2. **Write clear commit messages:** Follow the Conventional Commits format when possible:
   - `feat: add support for PDF download`
   - `fix: resolve issue with empty job description`
   - `docs: update API documentation`
3. **Verify tests:** Ensure all tests pass locally before opening a PR.
4. **Update docs:** If your changes affect configuration, endpoints, or behavior, update the relevant files in `docs/` and `README.md`.
5. **Open the PR:** Fill out the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md) completely with a clear description of the change and test steps.

---

## Reporting Issues

If you find a bug or have a suggestion:
1. Check the [issue tracker](https://github.com/dreww01/resume-maker/issues) first to make sure it has not been reported already.
2. Open a new issue using the appropriate template:
   - **Bug Report:** Include reproduction steps, expected behavior, actual behavior, and environment details.
   - **Feature Request:** Clearly describe the problem you want solved and your proposed solution.

---

## Questions and Support

If you need help or have questions, feel free to open a discussion or issue in the GitHub repository.

Thank you for helping make Resume Tailor better!
