"""Streamlit frontend web application for Resume Tailor.

Provides an interactive user interface for uploading resumes, entering job descriptions,
triggering AI tailoring and cover letter generation, and downloading formatted DOCX artifacts.
"""

import os
from typing import Any, Optional
from dotenv import load_dotenv
import requests  # type: ignore[import-untyped]
import streamlit as st

load_dotenv()

API_URL: str = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Resume Tailor", page_icon="📄", layout="centered")
st.title("Resume Tailor & Cover Letter Generator")

if "resume_id" not in st.session_state:
    st.session_state.resume_id = None
if "status" not in st.session_state:
    st.session_state.status = None

uploaded_file = st.file_uploader("Upload your resume", type=["pdf", "docx"])

if uploaded_file and st.session_state.resume_id is None:
    with st.spinner("Uploading..."):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        try:
            response = requests.post(f"{API_URL}/upload", files=files, timeout=30)
            if response.status_code in (200, 201):
                data = response.json()
                st.session_state.resume_id = data["id"]
                st.session_state.status = data.get("status", "uploaded")
                st.success(f"Uploaded: {data['filename']}")
            else:
                error_detail = response.json().get("detail", "Ensure file is PDF or DOCX.") if response.headers.get("content-type", "").startswith("application/json") else "Ensure file is PDF or DOCX."
                st.error(f"Upload failed: {error_detail}")
        except requests.RequestException as e:
            st.error(f"Connection error to API: {e}")

if st.session_state.resume_id:
    st.info(f"Status: {st.session_state.status}")

job_description = st.text_area("Paste the job description", height=200)

col1, col2 = st.columns(2)

with col1:
    if st.button("Tailor Resume", disabled=not st.session_state.resume_id or not job_description or len(job_description.strip()) < 10):
        with st.spinner("Tailoring resume..."):
            try:
                response = requests.post(
                    f"{API_URL}/resumes/{st.session_state.resume_id}/tailor",
                    json={"job_description": job_description},
                    headers={"Content-Type": "application/json"},
                    timeout=120,
                )
                if response.status_code == 200:
                    st.session_state.status = "completed"
                    st.success("Resume tailored!")
                else:
                    detail = response.json().get("detail", "Tailoring failed.") if response.headers.get("content-type", "").startswith("application/json") else "Tailoring failed."
                    st.error(f"Tailoring failed: {detail}")
            except requests.RequestException as e:
                st.error(f"API request failed: {e}")

with col2:
    if st.button("Generate Cover Letter", disabled=not st.session_state.resume_id or not job_description or len(job_description.strip()) < 10):
        with st.spinner("Generating cover letter..."):
            try:
                response = requests.post(
                    f"{API_URL}/resumes/{st.session_state.resume_id}/cover-letter",
                    json={"job_description": job_description},
                    headers={"Content-Type": "application/json"},
                    timeout=120,
                )
                if response.status_code == 200:
                    st.success("Cover letter generated!")
                else:
                    detail = response.json().get("detail", "Generation failed.") if response.headers.get("content-type", "").startswith("application/json") else "Generation failed."
                    st.error(f"Generation failed: {detail}")
            except requests.RequestException as e:
                st.error(f"API request failed: {e}")

st.divider()
st.subheader("Downloads")

dl_col1, dl_col2 = st.columns(2)

with dl_col1:
    if st.button("Download Tailored Resume", disabled=not st.session_state.resume_id):
        try:
            response = requests.get(f"{API_URL}/resumes/{st.session_state.resume_id}/download", timeout=30)
            if response.status_code == 200:
                filename = response.headers.get("content-disposition", "").split("filename=")[-1].strip('"') or "tailored_resume.docx"
                st.download_button(
                    "Save Resume",
                    response.content,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            else:
                st.error("Resume not ready. Tailor it first.")
        except requests.RequestException as e:
            st.error(f"Failed to fetch download: {e}")

with dl_col2:
    if st.button("Download Cover Letter", disabled=not st.session_state.resume_id):
        try:
            response = requests.get(f"{API_URL}/resumes/{st.session_state.resume_id}/cover-letter/download", timeout=30)
            if response.status_code == 200:
                filename = response.headers.get("content-disposition", "").split("filename=")[-1].strip('"') or "cover_letter.docx"
                st.download_button(
                    "Save Cover Letter",
                    response.content,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            else:
                st.error("Cover letter not ready. Generate it first.")
        except requests.RequestException as e:
            st.error(f"Failed to fetch download: {e}")

if st.button("Reset"):
    st.session_state.resume_id = None
    st.session_state.status = None
    st.rerun()
