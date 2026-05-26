from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from nature_track.openalex import Article, ArticleQuery


EMAIL_PROVIDERS = {
    "QQ Mail": {"smtp_host": "smtp.qq.com", "smtp_port": 587, "use_tls": True},
    "163 Mail": {"smtp_host": "smtp.163.com", "smtp_port": 465, "use_tls": False},
    "Gmail": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "use_tls": True},
    "Outlook": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "use_tls": True},
    "Custom": {"smtp_host": "", "smtp_port": 587, "use_tls": True},
}


@dataclass(frozen=True)
class EmailSettings:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    sender: str
    recipient: str
    use_tls: bool = True


def send_digest_email(settings: EmailSettings, query: ArticleQuery, articles: list[Article]) -> None:
    _validate_settings(settings)

    message = EmailMessage()
    message["Subject"] = f"Nature-track digest: {len(articles)} papers"
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message.set_content(_render_text_digest(query, articles))

    if settings.smtp_port == 465 and not settings.use_tls:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def _validate_settings(settings: EmailSettings) -> None:
    missing = [
        field
        for field in ["smtp_host", "sender", "recipient", "smtp_password"]
        if not getattr(settings, field)
    ]
    if missing:
        raise ValueError("Missing email settings: " + ", ".join(missing))


def _render_text_digest(query: ArticleQuery, articles: list[Article]) -> str:
    lines = [
        "Nature-track digest",
        f"Date window: {query.from_date.isoformat()} to {query.to_date.isoformat()}",
        f"Journals: {', '.join(query.journals)}",
        f"Keywords: {query.keywords or 'none'}",
        "",
    ]

    if not articles:
        lines.append("No matching articles found.")
        return "\n".join(lines)

    for index, article in enumerate(articles, start=1):
        lines.extend(
            [
                f"{index}. {article.compact_label}",
                f"   DOI: {article.doi or 'none'}",
                f"   URL: {article.doi_url or article.landing_page_url or 'none'}",
                f"   PDF: {article.pdf_url or 'none'}",
                "",
            ]
        )

    return "\n".join(lines)
