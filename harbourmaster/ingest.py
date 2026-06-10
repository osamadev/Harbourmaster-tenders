"""Helpers for extracting plain text from uploaded tender/policy files."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader


def extract_text(uploaded_file: Any) -> str:
    """Extract UTF-8 text from Streamlit uploaded file objects.

    Supported:
    - PDF (`application/pdf`)
    - Text-like files (`text/*`, markdown/txt)
    """
    if uploaded_file is None:
        return ""

    name = str(getattr(uploaded_file, "name", "") or "")
    mime = str(getattr(uploaded_file, "type", "") or "")
    raw = uploaded_file.getvalue()
    if not isinstance(raw, (bytes, bytearray)):
        return ""
    blob = bytes(raw)

    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        return _extract_pdf(blob)

    if mime.startswith("text/") or name.lower().endswith((".md", ".txt", ".csv", ".yaml", ".yml", ".json")):
        return _decode_bytes(blob)

    # Best-effort fallback.
    return _decode_bytes(blob)


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return ""


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
    except Exception:  # noqa: BLE001
        return ""

    chunks: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        text = text.strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()
