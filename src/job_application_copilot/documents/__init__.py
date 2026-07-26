"""Local document validation helpers."""

from job_application_copilot.documents.docx_validation import (
    MAX_DOCX_BYTES,
    MAX_DOCX_UNCOMPRESSED_BYTES,
    DocxValidationError,
    validate_docx,
)

__all__ = [
    "MAX_DOCX_BYTES",
    "MAX_DOCX_UNCOMPRESSED_BYTES",
    "DocxValidationError",
    "validate_docx",
]
