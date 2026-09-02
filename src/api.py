"""FastAPI backend application for Resume Tailor.

Exposes REST endpoints with strict Pydantic v2 validation schemas,
standardized HTTP status codes, and modular database/AI service integration.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.database import create_resume, get_resume_model, update_resume
from src.resume_processor import (
    call_openai,
    call_openai_cover_letter,
    create_cover_letter_docx,
    create_docx,
    read_resume,
)
from src.schemas import (
    CoverLetterRequest,
    CoverLetterResponse,
    ErrorResponse,
    ResumeResponse,
    ResumeUploadResponse,
    RootResponse,
    TailorResumeRequest,
    TailorResumeResponse,
)

logger = logging.getLogger(__name__)

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(
    title="Resume Tailor API",
    description="AI-powered resume tailoring and ATS-optimized document generator API.",
    version="0.1.0",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/",
    response_model=RootResponse,
    status_code=status.HTTP_200_OK,
    summary="Root Welcome & Health",
    description="Returns welcome status message for API root.",
)
async def root() -> RootResponse:
    """Return welcome message and interactive documentation link."""
    return RootResponse(message="Welcome to Resume Tailor API, Go to /docs to get started")


@app.post(
    "/upload",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Resume File",
    description="Accepts a .pdf or .docx resume file and stores it in the database.",
    responses={
        status.HTTP_201_CREATED: {"model": ResumeUploadResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    },
)
async def upload_resume(
    response: Response,
    file: UploadFile = File(..., description="Resume file in .pdf or .docx format."),
) -> ResumeUploadResponse:
    """Upload resume document and initialize tracking record in database.

    Args:
        response: FastAPI response object for customizing headers/status.
        file: Multipart file upload payload.

    Returns:
        ResumeUploadResponse containing the created resume ID, filename, status, and created_at.

    Raises:
        HTTPException: 400 Bad Request if file extension is not .pdf or .docx.
    """
    filename = file.filename or "resume"
    lower_filename = filename.lower()
    if not (lower_filename.endswith(".pdf") or lower_filename.endswith(".docx")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be .pdf or .docx",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    resume_id = create_resume(filename, content)
    resume = get_resume_model(resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist resume record.",
        )

    response.status_code = status.HTTP_201_CREATED
    return ResumeUploadResponse(
        id=resume.id,
        filename=resume.original_filename,
        status=resume.status,
        created_at=resume.created_at,
    )


@app.post(
    "/resumes/{resume_id}/tailor",
    response_model=TailorResumeResponse,
    status_code=status.HTTP_200_OK,
    summary="Tailor Resume",
    description="Tailor resume against job description using AI synthesis and generate DOCX.",
    responses={
        status.HTTP_200_OK: {"model": TailorResumeResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def tailor_resume(
    resume_id: int,
    request: Request,
) -> TailorResumeResponse:
    """Tailor an existing uploaded resume against the target job description.

    Supports both JSON body (`{"job_description": "..."}`) and raw plain text body.

    Args:
        resume_id: Unique database primary key of the resume.
        request: FastAPI Request instance for dynamic body parsing.

    Returns:
        TailorResumeResponse containing completion status and candidate user_name.

    Raises:
        HTTPException: 404 if resume not found, 400 for validation errors, 502 on upstream AI failure.
    """
    resume = get_resume_model(resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    content_type = request.headers.get("content-type", "")
    body_bytes = await request.body()
    job_description_text = ""

    if "application/json" in content_type:
        try:
            body_json = await request.json()
            validated_req = TailorResumeRequest.model_validate(body_json)
            job_description_text = validated_req.job_description
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON request body: {exc}",
            )
    else:
        # Plain text or fallback
        job_description_text = body_bytes.decode("utf-8", errors="replace").strip()
        if len(job_description_text) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description must be at least 10 characters.",
            )

    update_resume(resume_id, status="processing", job_description=job_description_text)

    try:
        resume_text = read_resume(resume.file_content, resume.original_filename)
    except Exception as exc:
        logger.error("Failed to read resume file: %s", exc, exc_info=True)
        update_resume(resume_id, status="failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to extract text from resume: {exc}",
        )

    try:
        tailored_data = call_openai(resume_text, job_description_text)
    except Exception as exc:
        logger.error("AI service error during resume tailoring: %s", exc, exc_info=True)
        update_resume(resume_id, status="failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream AI service failure: {exc}",
        )

    try:
        output_bytes = create_docx(tailored_data)
    except Exception as exc:
        logger.error("Failed to generate DOCX document: %s", exc, exc_info=True)
        update_resume(resume_id, status="failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate Word document: {exc}",
        )

    user_name = str(tailored_data.get("name", "") or "").strip()
    update_resume(
        resume_id,
        status="completed",
        output_content=output_bytes,
        user_name=user_name,
    )

    return TailorResumeResponse(status="completed", user_name=user_name)


@app.post(
    "/resumes/{resume_id}/cover-letter",
    response_model=CoverLetterResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Cover Letter",
    description="Generate customized cover letter matching candidate experience to job requirements.",
    responses={
        status.HTTP_200_OK: {"model": CoverLetterResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def generate_cover_letter(
    resume_id: int,
    request: Request,
) -> CoverLetterResponse:
    """Generate a cover letter for the specified resume ID and target job description.

    Args:
        resume_id: Unique database primary key of the resume.
        request: FastAPI Request instance.

    Returns:
        CoverLetterResponse with completion status and candidate user_name.

    Raises:
        HTTPException: 404 if resume not found, 400 for validation errors, 502 on upstream AI failure.
    """
    resume = get_resume_model(resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    content_type = request.headers.get("content-type", "")
    body_bytes = await request.body()
    job_description_text = ""

    if "application/json" in content_type:
        try:
            body_json = await request.json()
            validated_req = CoverLetterRequest.model_validate(body_json)
            job_description_text = validated_req.job_description
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON request body: {exc}",
            )
    else:
        job_description_text = body_bytes.decode("utf-8", errors="replace").strip()
        if len(job_description_text) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description must be at least 10 characters.",
            )

    try:
        resume_text = read_resume(resume.file_content, resume.original_filename)
    except Exception as exc:
        logger.error("Failed to read resume file: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to extract text from resume: {exc}",
        )

    try:
        cover_letter_data = call_openai_cover_letter(resume_text, job_description_text)
    except Exception as exc:
        logger.error("AI service error during cover letter synthesis: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream AI service failure: {exc}",
        )

    try:
        content_text = cover_letter_data.get("content", "")
        output_bytes = create_cover_letter_docx(content_text)
    except Exception as exc:
        logger.error("Failed to generate cover letter DOCX: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate cover letter Word document: {exc}",
        )

    user_name = str(cover_letter_data.get("name", "") or "").strip()
    update_resume(
        resume_id,
        cover_letter_content=output_bytes,
        user_name=user_name if user_name else resume.user_name,
    )

    return CoverLetterResponse(status="completed", user_name=user_name)


@app.get(
    "/resumes/{resume_id}",
    response_model=ResumeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Resume Status & Metadata",
    description="Retrieve processing status, filenames, timestamps, and generation flags for a resume.",
    responses={
        status.HTTP_200_OK: {"model": ResumeResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
def get_resume_status(resume_id: int) -> ResumeResponse:
    """Retrieve metadata and artifact generation flags for a resume record.

    Args:
        resume_id: Primary key integer of the resume.

    Returns:
        Typed ResumeResponse schema.

    Raises:
        HTTPException: 404 Not Found if resume does not exist.
    """
    resume = get_resume_model(resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    return ResumeResponse(
        id=resume.id,
        filename=resume.original_filename,
        original_filename=resume.original_filename,
        user_name=resume.user_name,
        created_at=resume.created_at,
        status=resume.status,
        has_tailored_resume=resume.has_tailored_resume,
        has_cover_letter=resume.has_cover_letter,
        has_output=resume.has_tailored_resume,
    )


@app.get(
    "/resumes/{resume_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Download Tailored Resume",
    description="Download the generated tailored resume in DOCX format.",
    responses={
        status.HTTP_200_OK: {
            "content": {DOCX_MIME_TYPE: {}},
            "description": "DOCX Word document binary stream.",
        },
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
def download_resume(resume_id: int) -> Response:
    """Stream generated tailored resume DOCX file.

    Args:
        resume_id: Primary key integer of the resume.

    Returns:
        Binary Response with Word document content and attachment headers.

    Raises:
        HTTPException: 404 if not found or no output, 400 if status is not completed.
    """
    resume = get_resume_model(resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    if resume.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume not ready for download",
        )

    if not resume.output_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output file not found",
        )

    safe_name = (resume.user_name or "unknown").replace(" ", "_")
    filename = f"{safe_name}_resume_{resume_id}.docx"

    return Response(
        content=resume.output_content,
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
    "/resumes/{resume_id}/cover-letter/download",
    status_code=status.HTTP_200_OK,
    summary="Download Cover Letter",
    description="Download the generated cover letter in DOCX format.",
    responses={
        status.HTTP_200_OK: {
            "content": {DOCX_MIME_TYPE: {}},
            "description": "DOCX Word document binary stream.",
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
def download_cover_letter(resume_id: int) -> Response:
    """Stream generated cover letter DOCX file.

    Args:
        resume_id: Primary key integer of the resume.

    Returns:
        Binary Response with Word document content and attachment headers.

    Raises:
        HTTPException: 404 if resume or cover letter content is not found.
    """
    resume = get_resume_model(resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    if not resume.cover_letter_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cover letter not found",
        )

    safe_name = (resume.user_name or "unknown").replace(" ", "_")
    filename = f"{safe_name}_cover_letter_{resume_id}.docx"

    return Response(
        content=resume.cover_letter_content,
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
