import logging
import smtplib
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger(__name__)


def send_hr_application_notification(
    settings: Settings,
    *,
    reference: str,
    full_name: str,
    email: str,
    phone: str,
    position: str,
    qualification: str,
    experience_years: str,
    skills: str,
    current_location: str,
    notice_period: str,
    resume_filename: str,
    resume_content_type: str,
    resume_content: bytes,
) -> None:
    """Notify HR without exposing applicant data in logs when SMTP is unavailable."""
    if not settings.smtp_host or not settings.smtp_from_email or not settings.hr_notification_email:
        logger.info("Career application saved; HR email notification is not configured")
        return

    message = EmailMessage()
    message["Subject"] = f"New candidate for HR review - {position} - {reference}"
    message["From"] = settings.smtp_from_email
    message["To"] = settings.hr_notification_email
    message.set_content(
        "\n".join(
            [
                "A new careers application requires HR review.",
                "",
                f"Reference: {reference}",
                f"Candidate: {full_name}",
                f"Email: {email}",
                f"Phone: {phone}",
                f"Position: {position}",
                f"Qualification: {qualification}",
                f"Relevant experience: {experience_years}",
                f"Skills: {skills}",
                f"Location: {current_location}",
                f"Notice period: {notice_period}",
                "",
                "This application has not been automatically shortlisted or rejected.",
            ]
        )
    )
    maintype, subtype = (resume_content_type.split("/", 1) + ["octet-stream"])[:2]
    message.add_attachment(resume_content, maintype=maintype, subtype=subtype, filename=resume_filename)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except Exception:
        logger.exception("HR email notification failed for a saved career application")
