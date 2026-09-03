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
from job_application_copilot.documents.french_reference_extraction import (
    FrenchReferenceExtractionError,
    extract_french_reference_text,
)

__all__ = [
    "DocumentBExtractionError",
    "ExtractedDocumentBSection",
    "MAX_DOCX_BYTES",
    "MAX_DOCX_UNCOMPRESSED_BYTES",
    "DocxValidationError",
    "CvDocumentRenderError",
    "extract_document_b_sections",
    "FrenchReferenceExtractionError",
    "extract_french_reference_text",
    "render_cv_template",
    "validate_docx",
]
