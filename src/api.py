from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from src.database import create_resume, get_resume, update_resume
from src.resume_processor import read_resume, call_openai, create_docx, call_openai_cover_letter, create_cover_letter_docx
from src.security import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    rate_limit_dependency,
    verify_linear_hmac,
    verify_github_hmac,
    rate_limiter,
)

app = FastAPI(title="Resume Tailor API")

# Middlewares are executed in reverse order of addition in Starlette/FastAPI:
# 1. RequestSizeLimitMiddleware (rejects large payloads before processing)
# 2. SecurityHeadersMiddleware (outermost for response headers, ensuring headers are set even on errors)
# 3. CORSMiddleware
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/webhook/linear", dependencies=[Depends(rate_limit_dependency)])
async def linear_webhook(
    request: Request,
    linear_signature: str | None = Header(None, alias="Linear-Signature")
):
    body = await request.body()
    if not verify_linear_hmac(linear_signature, body):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return {"status": "ok"}


@app.post("/webhook/github", dependencies=[Depends(rate_limit_dependency)])
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256")
):
    body = await request.body()
    if not verify_github_hmac(x_hub_signature_256, body):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return {"status": "ok"}


@app.post("/api/thinking", dependencies=[Depends(rate_limit_dependency)])
@app.get("/api/thinking", dependencies=[Depends(rate_limit_dependency)])
async def thinking():
    return {"status": "thinking"}


@app.get("/")
async def root():
    return {"message": "Welcome to Resume Tailor API, Go to /docs to get started"}


@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    if not file.filename.endswith(('.pdf', '.docx')):
        raise HTTPException(400, "File must be .pdf or .docx")

    content = await file.read()
    resume_id = create_resume(file.filename, content)

    return {"id": resume_id, "filename": file.filename}


@app.post("/resumes/{resume_id}/tailor")
def tailor_resume(resume_id: int, job_description: str = Body(..., media_type="text/plain")):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    update_resume(resume_id, status="processing", job_description=job_description)

    resume_text = read_resume(resume["file_content"], resume["original_filename"])
    tailored_data = call_openai(resume_text, job_description)

    output_bytes = create_docx(tailored_data)
    user_name = tailored_data.get("name", "")

    update_resume(resume_id, status="completed", output_content=output_bytes, user_name=user_name)

    return {"status": "completed", "user_name": user_name}


@app.post("/resumes/{resume_id}/cover-letter")
def generate_cover_letter(resume_id: int, job_description: str = Body(..., media_type="text/plain")):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    resume_text = read_resume(resume["file_content"], resume["original_filename"])
    cover_letter_data = call_openai_cover_letter(resume_text, job_description)

    output_bytes = create_cover_letter_docx(cover_letter_data["content"])
    user_name = cover_letter_data.get("name", "")

    update_resume(resume_id, cover_letter_content=output_bytes, user_name=user_name)

    return {"status": "completed", "user_name": user_name}


@app.get("/resumes/{resume_id}")
def get_resume_status(resume_id: int):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    return {
        "id": resume["id"],
        "original_filename": resume["original_filename"],
        "user_name": resume["user_name"],
        "created_at": resume["created_at"],
        "status": resume["status"],
        "has_output": resume["output_content"] is not None,
        "has_cover_letter": resume["cover_letter_content"] is not None
    }


@app.get("/resumes/{resume_id}/download")
def download_resume(resume_id: int):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    if resume["status"] != "completed":
        raise HTTPException(400, "Resume not ready for download")

    if not resume["output_content"]:
        raise HTTPException(404, "Output file not found")

    safe_name = (resume["user_name"] or "unknown").replace(" ", "_")
    filename = f"{safe_name}_resume_{resume_id}.docx"

    return Response(
        content=resume["output_content"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/resumes/{resume_id}/cover-letter/download")
def download_cover_letter(resume_id: int):
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")

    if not resume["cover_letter_content"]:
        raise HTTPException(404, "Cover letter not found")

    safe_name = (resume["user_name"] or "unknown").replace(" ", "_")
    filename = f"{safe_name}_cover_letter_{resume_id}.docx"

    return Response(
        content=resume["cover_letter_content"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
