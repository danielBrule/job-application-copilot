"""Local document validation helpers."""

from job_application_copilot.documents.cv_renderer import CvDocumentRenderError, render_cv_template
from job_application_copilot.documents.document_b_extraction import (
    DocumentBExtractionError,
    ExtractedDocumentBSection,
    extract_document_b_sections,
)
from job_application_copilot.documents.docx_validation import (
    MAX_DOCX_BYTES,
    MAX_DOCX_UNCOMPRESSED_BYTES,
    DocxValidationError,
    validate_docx,
)

__all__ = [
    "DocumentBExtractionError",
    "ExtractedDocumentBSection",
    "MAX_DOCX_BYTES",
    "MAX_DOCX_UNCOMPRESSED_BYTES",
    "DocxValidationError",
    "CvDocumentRenderError",
    "extract_document_b_sections",
    "render_cv_template",
    "validate_docx",
]
