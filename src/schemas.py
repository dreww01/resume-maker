"""Pydantic v2 schemas for API request and response models, and AI output validation."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# API Input / Output Schemas
# ---------------------------------------------------------------------------

class RootResponse(BaseModel):
    """Schema for root health/welcome response."""
    message: str = Field(
        ...,
        description="Welcome and orientation message for the API.",
        examples=["Welcome to Resume Tailor API, Go to /docs to get started"]
    )


class ResumeUploadResponse(BaseModel):
    """Schema returned after a successful resume file upload."""
    id: int = Field(..., description="Unique database identifier for the uploaded resume.")
    filename: str = Field(..., description="Original name of the uploaded resume file.")
    status: str = Field(..., description="Current processing status (e.g., 'uploaded').")
    created_at: datetime = Field(..., description="UTC timestamp when the resume record was created.")

    model_config = {
        "from_attributes": True,
    }


class TailorResumeRequest(BaseModel):
    """Schema for requesting resume tailoring or cover letter generation."""
    job_description: str = Field(
        ...,
        min_length=10,
        description="Target job description text (minimum 10 characters).",
        examples=["Looking for a Senior Python Engineer with FastAPI and AI experience..."]
    )


class CoverLetterRequest(BaseModel):
    """Schema for cover letter generation request."""
    job_description: str = Field(
        ...,
        min_length=10,
        description="Target job description text (minimum 10 characters).",
        examples=["Looking for a Senior Python Engineer with FastAPI and AI experience..."]
    )


class TailorResumeResponse(BaseModel):
    """Schema returned upon successful resume tailoring."""
    status: str = Field(..., description="Processing status, typically 'completed'.")
    user_name: Optional[str] = Field(None, description="Candidate name extracted and tailored.")


class CoverLetterResponse(BaseModel):
    """Schema returned upon successful cover letter generation."""
    status: str = Field(..., description="Processing status, typically 'completed'.")
    user_name: Optional[str] = Field(None, description="Candidate name extracted.")


class ResumeResponse(BaseModel):
    """Schema representing complete metadata and status of a resume record."""
    id: int = Field(..., description="Unique resume identifier.")
    filename: str = Field(..., description="Original uploaded filename.")
    user_name: Optional[str] = Field(None, description="Candidate name if extracted.")
    status: str = Field(..., description="Current status of the resume processing lifecycle.")
    has_tailored_resume: bool = Field(
        ...,
        description="Whether a tailored resume DOCX binary is generated and available."
    )
    has_cover_letter: bool = Field(
        ...,
        description="Whether a customized cover letter DOCX binary is generated and available."
    )
    created_at: datetime = Field(..., description="UTC creation timestamp.")
    original_filename: Optional[str] = Field(
        None,
        description="Alias for filename for backward compatibility."
    )
    has_output: Optional[bool] = Field(
        None,
        description="Alias for has_tailored_resume for backward compatibility."
    )

    model_config = {
        "from_attributes": True,
    }


class ErrorResponse(BaseModel):
    """Standardized error payload schema."""
    detail: str = Field(..., description="Descriptive error explanation.")
    error_code: Optional[str] = Field(None, description="Optional machine-readable error code.")


# ---------------------------------------------------------------------------
# AI Structured Output Data Models & Validation Schemas
# ---------------------------------------------------------------------------

class WorkExperienceItem(BaseModel):
    """Schema for an individual work experience entry."""
    title: str = Field(..., description="Job title / role.")
    company: str = Field(..., description="Company or organization name.")
    duration: str = Field(..., description="Time period worked (e.g., '2021 - Present').")
    bullets: list[str] = Field(
        default_factory=list,
        description="List of achievement bullet points."
    )


class ProjectItem(BaseModel):
    """Schema for a project entry."""
    name: str = Field(..., description="Project name.")
    bullets: list[str] = Field(
        default_factory=list,
        description="List of project highlights and contributions."
    )


class EducationItem(BaseModel):
    """Schema for an education entry."""
    degree: str = Field(..., description="Degree or certificate name.")
    institution: str = Field(..., description="University or educational institution.")
    year: str = Field(..., description="Graduation year or date range.")


class TailoredResumeData(BaseModel):
    """Schema validating structured JSON returned by AI resume tailoring."""
    name: str = Field(..., description="Candidate full name.")
    email: Optional[str] = Field(default="", description="Contact email address.")
    phone: Optional[str] = Field(default="", description="Contact phone number.")
    location: Optional[str] = Field(default="", description="Location (city, state/country).")
    github: Optional[str] = Field(default="", description="GitHub profile URL or handle.")
    linkedin: Optional[str] = Field(default="", description="LinkedIn profile URL or handle.")
    portfolio: Optional[str] = Field(default="", description="Portfolio website URL.")
    professional_summary: Optional[str] = Field(
        default="",
        description="Tailored professional summary paragraph."
    )
    work_experience: list[WorkExperienceItem] = Field(
        default_factory=list,
        description="List of work experience entries."
    )
    projects: list[ProjectItem] = Field(
        default_factory=list,
        description="List of relevant key projects."
    )
    skills: list[str] = Field(
        default_factory=list,
        description="List of technical skills."
    )
    soft_skills: list[str] = Field(
        default_factory=list,
        description="List of soft skills and core competencies."
    )
    education: list[EducationItem] = Field(
        default_factory=list,
        description="List of educational credentials."
    )


class CoverLetterData(BaseModel):
    """Schema validating structured JSON returned by AI cover letter generation."""
    name: Optional[str] = Field(default="", description="Candidate full name.")
    content: str = Field(..., description="Full text body of the cover letter.")
