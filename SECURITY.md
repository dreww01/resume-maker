# Security Policy

We take the security of Resume Tailor seriously. This document outlines our policy for reporting and handling potential security vulnerabilities.

---

## Supported Versions

We provide security updates and patches for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| `0.1.x` | :white_check_mark: |
| `< 0.1` | :x:                |

---

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please follow these steps:

1. **Do not create a public issue.** Please avoid discussing vulnerabilities publicly in GitHub issues, pull requests, or forums.
2. **Report Privately:** Send a detailed report via GitHub Private Vulnerability Reporting or contact the repository maintainers.
3. **Include Helpful Details:** To help us reproduce and resolve the issue quickly, please include:
   - Type of vulnerability and potential impact.
   - Step-by-step instructions to reproduce the issue.
   - Any relevant logs, code samples, or proof-of-concept payloads.
   - Your name or pseudonym if you would like to be credited.

---

## What to Expect

- **Acknowledgment:** We will acknowledge receipt of your report within 48 hours.
- **Assessment:** We will confirm the vulnerability and assess its severity.
- **Resolution:** A fix will be developed, tested, and released as quickly as possible.
- **Public Disclosure:** Once a fix is released, we will publish a security advisory and credit the reporter (unless you request anonymity).

---

## Security Best Practices for Users

When self-hosting or deploying Resume Tailor:
- **API Keys:** Never commit `.env` files or API keys into version control.
- **Database Safety:** When using SQLite in production, store the database file in a secure, non-public directory.
- **Network Boundaries:** In production, restrict FastAPI backend exposure or place it behind a reverse proxy with TLS/HTTPS.
- **Input Validation:** Only upload trusted PDF and DOCX files to prevent unexpected parser issues.
