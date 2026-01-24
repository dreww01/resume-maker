import os
import json
import base64
import io
import tempfile
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openai import OpenAI
from dotenv import load_dotenv
import pypdfium2 as pdfium

from src.prompts.resume_tailor import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from src.prompts.cover_letter import COVER_LETTER_SYSTEM_PROMPT, COVER_LETTER_USER_TEMPLATE

load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o-mini")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")


def extract_pdf_with_vision(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        pdf = pdfium.PdfDocument(tmp_path)
        image_contents = []

        for page in pdf:
            bitmap = page.render(scale=2)
            pil_image = bitmap.to_pil()
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"}
            })
        pdf.close()
    finally:
        os.unlink(tmp_path)

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract ALL text from this resume image. Preserve the structure and sections. Return only the extracted text, no commentary."},
                *image_contents
            ]
        }],
        max_tokens=4000
    )

    return response.choices[0].message.content.strip()


def read_resume(file_bytes: bytes, filename: str) -> str:
    if filename.endswith('.pdf'):
        return extract_pdf_with_vision(file_bytes)

    elif filename.endswith('.docx'):
        doc = Document(io.BytesIO(file_bytes))
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text.strip()

    else:
        raise ValueError("File must be .pdf or .docx")


def call_openai(resume_text: str, job_description: str) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        resume_text=resume_text,
        job_description=job_description
    )

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


def call_openai_cover_letter(resume_text: str, job_description: str) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)
    user_prompt = COVER_LETTER_USER_TEMPLATE.format(
        resume_text=resume_text,
        job_description=job_description
    )

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": COVER_LETTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


def create_cover_letter_docx(text: str) -> bytes:
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    for paragraph in text.strip().split('\n\n'):
        if paragraph.strip():
            p = doc.add_paragraph(paragraph.strip())
            p.paragraph_format.space_after = Pt(12)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def create_docx(resume_data: dict) -> bytes:
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

    def add_section_heading(text):
        heading = doc.add_paragraph()
        heading_run = heading.add_run(text.upper())
        heading_run.bold = True
        heading_run.font.size = Pt(11)
        heading_run.font.color.rgb = RGBColor(0, 51, 102)
        heading.space_before = Pt(10)
        heading.space_after = Pt(2)

    # header
    name = doc.add_paragraph()
    name_run = name.add_run(resume_data['name'])
    name_run.bold = True
    name_run.font.size = Pt(20)
    name_run.font.color.rgb = RGBColor(0, 0, 0)
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.space_after = Pt(4)

    contact_parts = []
    for field in ['email', 'phone', 'location', 'github', 'linkedin', 'portfolio']:
        value = resume_data.get(field, '').strip()
        if value:
            contact_parts.append(value)

    contact = doc.add_paragraph()
    contact_run = contact.add_run(' | '.join(contact_parts))
    contact_run.font.size = Pt(10)
    contact_run.font.color.rgb = RGBColor(64, 64, 64)
    contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact.space_after = Pt(10)

    # professional summary
    if resume_data.get('professional_summary'):
        add_section_heading('Professional Summary')
        summary = doc.add_paragraph(resume_data['professional_summary'])
        summary.space_after = Pt(8)

    # professional experience
    add_section_heading('Professional Experience')
    for job in resume_data.get('work_experience', []):
        title_para = doc.add_paragraph()
        title_run = title_para.add_run(job['title'])
        title_run.bold = True
        title_run.font.size = Pt(11)
        title_para.space_after = Pt(2)

        company_para = doc.add_paragraph()
        company_run = company_para.add_run(f"{job['company']} | ")
        company_run.font.size = Pt(10)
        duration_run = company_para.add_run(job['duration'])
        duration_run.italic = True
        duration_run.font.size = Pt(10)
        duration_run.font.color.rgb = RGBColor(64, 64, 64)
        company_para.space_after = Pt(4)

        for bullet in job['bullets']:
            bullet_para = doc.add_paragraph(bullet, style='List Bullet')
            bullet_para.space_after = Pt(2)

        doc.add_paragraph().space_after = Pt(6)

    # key projects
    if resume_data.get('projects'):
        add_section_heading('Key Projects')
        for project in resume_data['projects']:
            project_para = doc.add_paragraph()
            name_run = project_para.add_run(project['name'])
            name_run.bold = True
            name_run.font.size = Pt(10.5)
            project_para.space_after = Pt(2)

            for bullet in project['bullets']:
                bullet_para = doc.add_paragraph(bullet, style='List Bullet')
                bullet_para.space_after = Pt(2)

            doc.add_paragraph().space_after = Pt(4)

    # technical skills
    if resume_data.get('skills'):
        add_section_heading('Technical Skills')
        skills_text = ' | '.join(resume_data['skills'])
        skills = doc.add_paragraph(skills_text)
        skills.space_after = Pt(8)

    # core competencies
    if resume_data.get('soft_skills'):
        add_section_heading('Core Competencies')
        soft_skills_text = ' | '.join(resume_data['soft_skills'])
        competencies = doc.add_paragraph(soft_skills_text)
        competencies.space_after = Pt(8)

    # education
    if resume_data.get('education'):
        add_section_heading('Education')
        for edu in resume_data['education']:
            edu_para = doc.add_paragraph()
            degree_run = edu_para.add_run(edu['degree'])
            degree_run.bold = True
            degree_run.font.size = Pt(10.5)
            edu_para.add_run(f" - {edu['institution']}, {edu['year']}")
            edu_para.space_after = Pt(4)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
