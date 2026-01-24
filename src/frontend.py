import streamlit as st
import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Resume Tailor", page_icon="", layout="centered")
st.title("Resume Tailor & Cover Letter Generator")

if "resume_id" not in st.session_state:
    st.session_state.resume_id = None
if "status" not in st.session_state:
    st.session_state.status = None

uploaded_file = st.file_uploader("Upload your resume", type=["pdf", "docx"])

if uploaded_file and st.session_state.resume_id is None:
    with st.spinner("Uploading..."):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        response = requests.post(f"{API_URL}/upload", files=files)
        if response.status_code == 200:
            data = response.json()
            st.session_state.resume_id = data["id"]
            st.session_state.status = "uploaded"
            st.success(f"Uploaded: {data['filename']}")
        else:
            st.error("Upload failed. Ensure file is PDF or DOCX.")

if st.session_state.resume_id:
    st.info(f"Status: {st.session_state.status}")

job_description = st.text_area("Paste the job description", height=200)

col1, col2 = st.columns(2)

with col1:
    if st.button("Tailor Resume", disabled=not st.session_state.resume_id or not job_description):
        with st.spinner("Tailoring resume..."):
            response = requests.post(
                f"{API_URL}/resumes/{st.session_state.resume_id}/tailor",
                data=job_description,
                headers={"Content-Type": "text/plain"}
            )
            if response.status_code == 200:
                st.session_state.status = "completed"
                st.success("Resume tailored!")
            else:
                st.error("Tailoring failed.")

with col2:
    if st.button("Generate Cover Letter", disabled=not st.session_state.resume_id or not job_description):
        with st.spinner("Generating cover letter..."):
            response = requests.post(
                f"{API_URL}/resumes/{st.session_state.resume_id}/cover-letter",
                data=job_description,
                headers={"Content-Type": "text/plain"}
            )
            if response.status_code == 200:
                st.success("Cover letter generated!")
            else:
                st.error("Generation failed.")

st.divider()
st.subheader("Downloads")

dl_col1, dl_col2 = st.columns(2)

with dl_col1:
    if st.button("Download Tailored Resume", disabled=not st.session_state.resume_id):
        response = requests.get(f"{API_URL}/resumes/{st.session_state.resume_id}/download")
        if response.status_code == 200:
            filename = response.headers.get("content-disposition", "").split("filename=")[-1].strip('"') or "tailored_resume.docx"
            st.download_button("Save Resume", response.content, file_name=filename, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.error("Resume not ready. Tailor it first.")

with dl_col2:
    if st.button("Download Cover Letter", disabled=not st.session_state.resume_id):
        response = requests.get(f"{API_URL}/resumes/{st.session_state.resume_id}/cover-letter/download")
        if response.status_code == 200:
            filename = response.headers.get("content-disposition", "").split("filename=")[-1].strip('"') or "cover_letter.docx"
            st.download_button("Save Cover Letter", response.content, file_name=filename, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.error("Cover letter not ready. Generate it first.")

if st.button("Reset"):
    st.session_state.resume_id = None
    st.session_state.status = None
    st.rerun()
