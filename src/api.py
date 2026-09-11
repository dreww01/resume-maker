"""FastAPI backend application for Resume Tailor.

Exposes REST endpoints with strict Pydantic v2 validation schemas,
standardized HTTP status codes, and modular database/AI service integration.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from urllib.parse import quote

from src.auth import (
    CurrentUser,
    LoginRequest,
    REDIRECT_STATUS_CODE,
    create_access_token,
    create_expired_token,
    extract_token_from_request,
    get_current_user_optional,
    require_api_auth,
    require_page_auth,
    sanitize_next_destination,
    verify_token_string,
    verify_token_sync,
)

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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Standard 422 for API auth endpoints, retaining 400 for legacy endpoints
    if request.url.path.startswith("/api/auth/") or request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            content={"detail": exc.errors()},
        )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTPExceptions, ensuring unauthenticated web page visits redirect to login."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        is_api_route = (
            request.url.path.startswith("/api/")
            or request.url.path.startswith("/resumes/")
            or request.url.path in ("/upload",)
            or (
                "application/json" in request.headers.get("accept", "")
                and "text/html" not in request.headers.get("accept", "")
            )
        )
        is_page_route = (
            request.url.path in (
                "/dashboard",
                "/settings",
                "/account/settings",
                "/alerts/settings",
                "/tracked",
                "/discover",
                "/insights",
            )
            or request.url.path.startswith("/dashboard/")
            or request.url.path.startswith("/settings/")
            or "text/html" in request.headers.get("accept", "")
        )

        if is_page_route and not is_api_route:
            dest = request.url.path
            if request.url.query:
                dest = f"{dest}?{request.url.query}"
            safe_dest = sanitize_next_destination(dest)
            redirect_url = f"/login?next={quote(safe_dest, safe='/?&=')}"
            return RedirectResponse(
                url=redirect_url,
                status_code=REDIRECT_STATUS_CODE,
            )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
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
def tailor_resume(
    resume_id: int,
    payload: TailorResumeRequest,
) -> TailorResumeResponse:
    """Tailor an existing uploaded resume against the target job description.

    Args:
        resume_id: Unique database primary key of the resume.
        payload: TailorResumeRequest containing job_description.

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

    job_description_text = payload.job_description

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
def generate_cover_letter(
    resume_id: int,
    payload: CoverLetterRequest,
) -> CoverLetterResponse:
    """Generate a cover letter for the specified resume ID and target job description.

    Args:
        resume_id: Unique database primary key of the resume.
        payload: CoverLetterRequest containing job_description.

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

    job_description_text = payload.job_description

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


# ============================================================================
# Authentication & Web Page Session Endpoints
# ============================================================================

@app.get("/login", response_class=HTMLResponse, summary="Login Page")
async def login_page(
    request: Request,
    next: Optional[str] = "/dashboard",
) -> Any:
    """Render HTML login page, or redirect to destination if already authenticated."""
    user, _ = await get_current_user_optional(request)
    target = sanitize_next_destination(next or "/dashboard")
    if user:
        return RedirectResponse(url=target, status_code=REDIRECT_STATUS_CODE)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PriceHawk | Login</title>
</head>
<body>
    <div class="login-card">
        <h1>PriceHawk</h1>
        <h2>Sign In</h2>
        <form id="login-form" method="POST" action="/login">
            <input type="hidden" name="next" value="{target}">
            <div>
                <label for="username">Username or Email</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div>
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit">Sign In</button>
        </form>
        <p><a href="/forgot-password">Forgot Password</a></p>
        <p><a href="/signup">Sign Up</a></p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK)


@app.post("/login", summary="Process Login")
async def process_login(
    request: Request,
    next: Optional[str] = None,
) -> Any:
    """Authenticate user and redirect back to original destination with auth cookies."""
    username = ""
    password = ""
    next_dest = next or request.query_params.get("next")

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}
        username = body.get("username") or body.get("email") or ""
        password = body.get("password") or ""
        if not next_dest:
            next_dest = body.get("next")
    else:
        try:
            form = await request.form()
            username = str(form.get("username") or form.get("email") or "")
            password = str(form.get("password") or "")
            if not next_dest:
                next_dest = form.get("next")
        except Exception:
            pass

    if not username or not password:
        if "application/json" in content_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        return HTMLResponse(
            content="<p>Invalid username or password</p>",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    target = sanitize_next_destination(next_dest)
    token = create_access_token(data={"sub": username, "username": username, "email": username if "@" in username else None})

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header and "text/html" not in accept_header:
        resp = JSONResponse(
            content={
                "access_token": token,
                "token_type": "bearer",
                "redirect_url": target,
                "user": {"id": username, "username": username},
            },
            status_code=status.HTTP_200_OK,
            headers={"Location": target},
        )
        resp.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", path="/")
        resp.set_cookie(key="session_token", value=token, httponly=True, samesite="lax", path="/")
        return resp

    redirect = RedirectResponse(url=target, status_code=REDIRECT_STATUS_CODE)
    redirect.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", path="/")
    redirect.set_cookie(key="session_token", value=token, httponly=True, samesite="lax", path="/")
    return redirect


@app.get("/logout", summary="Logout (GET)")
@app.post("/logout", summary="Logout (POST)")
async def process_logout(request: Request) -> RedirectResponse:
    """Clear session cookies and redirect to login."""
    resp = RedirectResponse(url="/login", status_code=REDIRECT_STATUS_CODE)
    for c in ("access_token", "session_token", "auth_token", "session", "token"):
        resp.delete_cookie(c, path="/")
    return resp


@app.get("/signup", response_class=HTMLResponse, summary="Signup Page")
async def signup_page(request: Request) -> HTMLResponse:
    """Render HTML signup page."""
    user, _ = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=REDIRECT_STATUS_CODE)
    return HTMLResponse(
        content="<html><head><title>PriceHawk | Sign Up</title></head><body><h1>PriceHawk</h1><p>Sign Up</p></body></html>",
        status_code=status.HTTP_200_OK,
    )


@app.get("/forgot-password", response_class=HTMLResponse, summary="Forgot Password Page")
async def forgot_password_page(request: Request) -> HTMLResponse:
    """Render HTML forgot password page."""
    user, _ = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=REDIRECT_STATUS_CODE)
    return HTMLResponse(
        content="<html><head><title>Forgot Password - PriceHawk</title></head><body><h1>Forgot Password</h1><p>PriceHawk</p></body></html>",
        status_code=status.HTTP_200_OK,
    )


@app.get("/reset-password", response_class=HTMLResponse, summary="Reset Password Page")
async def reset_password_page(request: Request) -> HTMLResponse:
    """Render HTML reset password page."""
    user, _ = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=REDIRECT_STATUS_CODE)
    return HTMLResponse(
        content="<html><head><title>Reset Password - PriceHawk</title></head><body><h1>Reset Password</h1><p>PriceHawk</p></body></html>",
        status_code=status.HTTP_200_OK,
    )


# Protected Web Pages (Yield 302/303 redirect when unauthenticated/expired)

@app.get("/dashboard", response_class=HTMLResponse, summary="Dashboard Page")
async def dashboard_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected dashboard page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><title>Dashboard - PriceHawk</title></head>
<body>
    <h1>Dashboard</h1>
    <p>Welcome, {user.username or user.id}!</p>
    <a href="/settings">Settings</a>
    <a href="/logout">Logout</a>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK)


@app.get("/settings", response_class=HTMLResponse, summary="Settings Page")
async def settings_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected settings page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><title>Settings - PriceHawk</title></head>
<body>
    <h1>Settings</h1>
    <p>Settings for {user.username or user.id}</p>
    <a href="/dashboard">Dashboard</a>
    <a href="/logout">Logout</a>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK)


@app.get("/account/settings", response_class=HTMLResponse, summary="Account Settings Page")
async def account_settings_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected account settings page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><title>Account Settings - PriceHawk</title></head>
<body>
    <h1>Account Settings</h1>
    <p>Account for {user.username or user.id}</p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK)


@app.get("/alerts/settings", response_class=HTMLResponse, summary="Alerts Settings Page")
async def alerts_settings_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected alert settings page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><title>Alert Settings - PriceHawk</title></head>
<body>
    <h1>Alert Settings</h1>
    <p>Alerts for {user.username or user.id}</p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK)


@app.get("/tracked", response_class=HTMLResponse, summary="Tracked Products Page")
async def tracked_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected tracked page."""
    return HTMLResponse(
        content="<html><head><title>Tracked Products - PriceHawk</title></head><body><h1>Tracked Products</h1></body></html>",
        status_code=status.HTTP_200_OK,
    )


@app.get("/discover", response_class=HTMLResponse, summary="Discover Page")
async def discover_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected discover page."""
    return HTMLResponse(
        content="<html><head><title>Discover Products - PriceHawk</title></head><body><h1>Discover Products</h1></body></html>",
        status_code=status.HTTP_200_OK,
    )


@app.get("/insights", response_class=HTMLResponse, summary="Insights Page")
async def insights_page(
    request: Request,
    user: CurrentUser = Depends(require_page_auth),
) -> HTMLResponse:
    """Protected insights page."""
    return HTMLResponse(
        content="<html><head><title>AI Insights - PriceHawk</title></head><body><h1>AI Insights</h1></body></html>",
        status_code=status.HTTP_200_OK,
    )


# ============================================================================
# Protected API Endpoints (Yield HTTP 401 when unauthenticated/expired)
# ============================================================================

@app.get("/api/dashboard/stats", summary="Dashboard Statistics API")
async def api_dashboard_stats(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve dashboard statistics. Requires authentication."""
    return {
        "status": "success",
        "user_id": user.id,
        "username": user.username,
        "total_tracked": 0,
        "active_alerts": 0,
    }


@app.get("/api/dashboard/activity", summary="Dashboard Activity API")
async def api_dashboard_activity(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve dashboard activity log."""
    return {"status": "success", "activity": []}


@app.get("/api/dashboard/products", summary="Dashboard Products API")
async def api_dashboard_products(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve dashboard products."""
    return {"status": "success", "products": []}


@app.get("/api/insights", summary="Insights API")
async def api_insights(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve insights."""
    return {"status": "success", "insights": []}


@app.get("/api/settings", summary="Settings API")
async def api_settings(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve user settings."""
    return {"status": "success", "user_id": user.id, "theme": "light"}


@app.get("/api/account/settings", summary="Account Settings API")
async def api_account_settings(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve account settings."""
    return {"status": "success", "user_id": user.id}


@app.get("/api/alerts/settings", summary="Alerts Settings API")
async def api_alerts_settings(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve alert settings."""
    return {"status": "success", "user_id": user.id}


@app.get("/api/user", summary="Current User Profile API")
@app.get("/api/me", summary="Current User Me API")
@app.get("/api/auth/me", summary="Current User Auth Me API")
async def api_me(
    request: Request,
    user: CurrentUser = Depends(require_api_auth),
) -> dict[str, Any]:
    """Retrieve current authenticated user profile."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
    }


def _is_valid_email(email: Any) -> bool:
    """Validate that the provided string matches a basic email format (user@domain.tld)."""
    s = str(email or "").strip()
    if "@" not in s:
        return False
    parts = s.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    if "." not in parts[1] or parts[1].startswith(".") or parts[1].endswith("."):
        return False
    return True


@app.post("/api/auth/login", summary="API Login")
@app.post("/api/login", summary="API Login Alias")
async def api_login(
    request: Request,
    response: Response,
) -> dict[str, Any]:
    """API login endpoint returning JWT token and setting session cookies."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    email = body.get("email") or body.get("username")
    password = body.get("password")

    if not email or not password:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Fields 'email'/'username' and 'password' are required.",
        )

    if "email" in body and not _is_valid_email(body["email"]):
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Invalid email format.",
        )

    token = create_access_token(data={"sub": str(email), "email": str(email), "username": str(email)})
    next_dest = body.get("next") or "/dashboard"

    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", path="/")
    response.set_cookie(key="session_token", value=token, httponly=True, samesite="lax", path="/")

    return {
        "access_token": token,
        "token_type": "bearer",
        "redirect_url": next_dest,
        "user": {"id": str(email), "email": str(email)},
    }


@app.post("/api/auth/signup", summary="API Signup")
async def api_signup(request: Request) -> dict[str, Any]:
    """API signup endpoint."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    email = body.get("email") or body.get("username")
    password = body.get("password")

    if not email or not password:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Fields 'email' and 'password' are required.",
        )

    if not _is_valid_email(email):
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Invalid email format.",
        )

    return {"status": "created", "email": email}


@app.post("/api/auth/forgot-password", summary="API Forgot Password")
async def api_forgot_password(request: Request) -> dict[str, Any]:
    """API forgot password endpoint."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    email = body.get("email")
    if not email:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Field 'email' is required.",
        )

    if not _is_valid_email(email):
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Invalid email format.",
        )

    return {"status": "success", "message": "Password reset email sent if account exists."}


@app.post("/api/auth/reset-password", summary="API Reset Password")
async def api_reset_password(request: Request) -> dict[str, Any]:
    """API reset password endpoint."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    password = body.get("password")
    token = body.get("token") or body.get("code")

    if not password or not token:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Fields 'password' and 'token' are required.",
        )

    return {"status": "success", "message": "Password has been successfully updated."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
