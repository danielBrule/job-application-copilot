"""Shared helpers for Streamlit application behavior tests."""

from io import BytesIO
from pathlib import Path

from docx import Document

APP_PATH = Path(__file__).parents[1] / "src" / "job_application_copilot" / "ui" / "app.py"
SETTINGS_APP_TIMEOUT = 30


def make_docx(text: str = "Reference content") -> bytes:
    """Build a minimal in-memory DOCX upload."""

    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()
