import re
import uuid
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.main_state import limiter
from app.models import CareerApplication, Conversation
from app.schemas import CareerApplicationCreate, CareerApplicationResponse
from app.services.career_notifications import send_hr_application_notification

router = APIRouter(prefix="/api/careers", tags=["careers"])
ALLOWED_RESUMES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}


def clean_filename(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name).strip()
    return safe[:255] or "resume"


def validate_resume_content(extension: str, content: bytes) -> None:
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="The uploaded PDF is not valid")
    if extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except BadZipFile as exc:
            raise HTTPException(status_code=400, detail="The uploaded DOCX is not valid") from exc
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise HTTPException(status_code=400, detail="The uploaded DOCX is not valid")


@router.post("/applications", response_model=CareerApplicationResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
def create_career_application(
    request: Request,
    background_tasks: BackgroundTasks,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    position: str = Form(...),
    qualification: str = Form(...),
    experience_years: str = Form(...),
    skills: str = Form(...),
    current_location: str = Form(...),
    notice_period: str = Form(...),
    consent_to_contact: bool = Form(...),
    current_company: str | None = Form(default=None),
    message: str | None = Form(default=None),
    conversation_id: uuid.UUID | None = Form(default=None),
    resume: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> CareerApplication:
    try:
        payload = CareerApplicationCreate(
            conversation_id=conversation_id,
            full_name=full_name,
            email=email,
            phone=phone,
            position=position,
            qualification=qualification,
            experience_years=experience_years,
            skills=skills,
            current_location=current_location,
            notice_period=notice_period,
            current_company=current_company or None,
            message=message or None,
            consent_to_contact=consent_to_contact,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False)) from exc

    if payload.conversation_id and not db.get(Conversation, payload.conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    settings = get_settings()
    filename = clean_filename(resume.filename or "")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_RESUMES or (resume.content_type or "") not in ALLOWED_RESUMES[extension]:
        raise HTTPException(status_code=400, detail="Resume must be a PDF or DOCX file")
    max_bytes = settings.max_resume_mb * 1024 * 1024
    content = resume.file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Resume file is empty")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Resume must be no larger than {settings.max_resume_mb} MB")
    validate_resume_content(extension, content)

    application_id = uuid.uuid4()
    reference = f"ITS-CAR-{application_id.hex[:8].upper()}"
    application = CareerApplication(
        id=application_id,
        reference=reference,
        **payload.model_dump(),
        resume_filename=filename,
        resume_content_type=resume.content_type or "application/octet-stream",
        resume_size_bytes=len(content),
        resume_content=content,
        status="new_hr_review",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    background_tasks.add_task(
        send_hr_application_notification,
        settings,
        reference=reference,
        full_name=payload.full_name,
        email=str(payload.email),
        phone=payload.phone,
        position=payload.position,
        qualification=payload.qualification,
        experience_years=payload.experience_years,
        skills=payload.skills,
        current_location=payload.current_location,
        notice_period=payload.notice_period,
        resume_filename=filename,
        resume_content_type=resume.content_type or "application/octet-stream",
        resume_content=content,
    )
    return application
