"""Unit tests for prompt templates."""

from src.prompts.cover_letter import (
    COVER_LETTER_SYSTEM_PROMPT,
    COVER_LETTER_USER_TEMPLATE,
)
from src.prompts.resume_tailor import (
    SYSTEM_PROMPT as RT_SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE as RT_USER_PROMPT,
)


def test_resume_tailor_prompt_template() -> None:
    """Verify resume tailor prompt template formats correctly."""
    formatted = RT_USER_PROMPT.format(
        resume_text="Sample Resume Text",
        job_description="Sample Job Description",
    )
    assert "Sample Resume Text" in formatted
    assert "Sample Job Description" in formatted
    assert len(RT_SYSTEM_PROMPT) > 0


def test_cover_letter_prompt_template() -> None:
    """Verify cover letter prompt template formats correctly."""
    formatted = COVER_LETTER_USER_TEMPLATE.format(
        resume_text="Sample Resume Text",
        job_description="Sample Job Description",
    )
    assert "Sample Resume Text" in formatted
    assert "Sample Job Description" in formatted
    assert len(COVER_LETTER_SYSTEM_PROMPT) > 0
