"""Best-effort owner email notifications for auth events.

Reads SMTP configuration from the environment and sends a short email when a user
registers or logs in. Failures are swallowed (logged) so they never block app usage.
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

logger = logging.getLogger("harbourmaster.notify")


def _enabled() -> bool:
    return str(os.getenv("NOTIFY_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}


def _smtp_config() -> dict[str, str] | None:
    host = os.getenv("SMTP_HOST", "").strip()
    recipient = os.getenv("OWNER_EMAIL", "").strip()
    if not host or not recipient:
        return None
    return {
        "host": host,
        "port": os.getenv("SMTP_PORT", "587").strip() or "587",
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "sender": (os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USERNAME", "")).strip(),
        "recipient": recipient,
        "use_tls": str(os.getenv("SMTP_USE_TLS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
    }


def send_owner_email(subject: str, body: str) -> bool:
    """Send an email to OWNER_EMAIL. Returns True on success, False otherwise."""
    if not _enabled():
        return False
    cfg = _smtp_config()
    if cfg is None:
        logger.info("Notify skipped: SMTP_HOST / OWNER_EMAIL not configured.")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg["sender"] or cfg["recipient"]
        msg["To"] = cfg["recipient"]
        msg.set_content(body)

        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=10) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["username"]:
                server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
        logger.info("Owner notification sent: %s", subject)
        return True
    except Exception as exc:  # noqa: BLE001 — notifications must never break the app
        logger.warning("Owner notification failed: %s", exc)
        return False


def notify_event(kind: str, *, name: str = "", email: str = "", method: str = "local") -> bool:
    """Notify the owner of a 'registered' or 'login' event."""
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    who = name or email or "a user"
    label = {"registered": "New registration", "login": "User login"}.get(kind, kind.title())
    subject = f"[Harbourmaster] {label}: {who}"
    body = (
        f"{label} on Harbourmaster.\n\n"
        f"Name:   {name or '(n/a)'}\n"
        f"Email:  {email or '(n/a)'}\n"
        f"Method: {method}\n"
        f"Time:   {when}\n"
    )
    return send_owner_email(subject, body)
