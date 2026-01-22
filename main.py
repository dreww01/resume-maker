import os
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from database import create_resume, get_resume, update_resume
from resume import read_resume, call_openai, create_docx

app = FastAPI(title="Resume Tailor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.get("/")
async def root():
    return {"message": "Welcome to Resume Tailor API, Go to /docs to get started"}

@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    if not file.filename.endswith(('.pdf', '.docx')):
        raise HTTPException(400, "File must be .pdf or .docx")

    resume_id = create_resume(file.filename)
    file_path = os.path.join(UPLOAD_DIR, f"{resume_id}_{file.filename}")

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    update_resume(resume_id, original_filename=file_path)

    return {"id": resume_id, "filename": file.filename}


@app.post("/resumes/{resume_id}/tailor")
def tailor_resume(resume_id: int, job_description: str = Body(..., media_type="text/plain")):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    update_resume(resume_id, status="processing", job_description=job_description)

    resume_text = read_resume(resume["original_filename"])
    tailored_data = call_openai(resume_text, job_description)

    output_path = os.path.join(OUTPUT_DIR, f"{resume_id}_tailored.docx")
    create_docx(tailored_data, output_path)

    user_name = tailored_data.get("name", "")
    update_resume(resume_id, status="completed", output_filename=output_path, user_name=user_name)

    return {"status": "completed", "output_filename": output_path}


@app.get("/resumes/{resume_id}")
def get_resume_status(resume_id: int):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")
    return resume


@app.get("/resumes/{resume_id}/download")
def download_resume(resume_id: int):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    if resume["status"] != "completed":
        raise HTTPException(400, "Resume not ready for download")

    if not resume["output_filename"] or not os.path.exists(resume["output_filename"]):
        raise HTTPException(404, "Output file not found")

    safe_name = (resume["user_name"] or "unknown").replace(" ", "_")
    return FileResponse(
        resume["output_filename"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{safe_name}_resume_{resume_id}.docx"
    )


if __name__ == "__main__":
    import uvicorn
    PORT = 5000
    uvicorn.run(app, host="127.0.0.1", port=PORT)
