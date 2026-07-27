"""Settings controls for Document A and Document B replacement workflows."""

from typing import Protocol

import streamlit as st

from job_application_copilot.domain import DOCUMENT_A_KEY, RequiredReferenceAsset
from job_application_copilot.errors import ApplicationStorageError, ApplicationValidationError
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services import (
    DocumentAProcessingError,
    DocumentBProcessingError,
)
from job_application_copilot.ui.components.reference_asset_replacement_state import (
    REPLACEMENT_ERROR_KEY,
    REPLACEMENT_SUCCESS_KEY,
    UploadedDocx,
    replacement_success_message,
)

logger = get_logger(__name__)


class DocumentAReplacementProcessor(Protocol):
    """Boundary for the combined Document A replacement workflow."""

    def replace_and_process(self, *, filename: str, content: bytes) -> ReferenceAsset:
        """Store, upload, and activate a Document A replacement."""


class DocumentBReplacementProcessor(Protocol):
    """Boundary for the combined Document B replacement workflow."""

    def replace_and_process(self, *, filename: str, content: bytes) -> ReferenceAsset:
        """Store, process, validate, and activate a Document B replacement."""


def render_reference_document_form(
    requirement: RequiredReferenceAsset,
    processor: DocumentAReplacementProcessor | DocumentBReplacementProcessor,
    *,
    asset_exists: bool,
) -> None:
    """Render one canonical document form without local-only asset controls."""

    with st.expander(f"Upload or replace {requirement.label}"):
        with st.form(
            f"replace_reference_asset_{requirement.asset_key}",
            clear_on_submit=True,
        ):
            upload = st.file_uploader(
                f"{requirement.label} DOCX",
                type=["docx"],
                key=f"reference_asset_file_{requirement.asset_key}",
            )
            if requirement.asset_key == DOCUMENT_A_KEY:
                st.caption(
                    "Validates and stores the file locally, uploads the complete DOCX to OpenAI, "
                    "then activates it. The current version remains active if the upload fails."
                )
            else:
                st.caption(
                    "Validates and stores the file locally, uploads it to OpenAI, verifies its "
                    "vector store, then activates it. The current version remains active if "
                    "processing fails."
                )
            submitted = st.form_submit_button(
                "Replace and activate with OpenAI"
                if asset_exists
                else "Upload and activate with OpenAI"
            )

        if submitted:
            _replace_and_process_document(
                processor,
                upload=upload,
                is_document_a=requirement.asset_key == DOCUMENT_A_KEY,
            )


def _replace_and_process_document(
    processor: DocumentAReplacementProcessor | DocumentBReplacementProcessor,
    *,
    upload: UploadedDocx | None,
    is_document_a: bool,
) -> None:
    if upload is None:
        st.error("Choose a DOCX file.")
        return

    label = "Document A" if is_document_a else "Document B"
    try:
        with st.spinner(f"Validating, uploading and activating {label} with OpenAI..."):
            asset = processor.replace_and_process(
                filename=upload.name,
                content=upload.getvalue(),
            )
    except (ApplicationStorageError, ApplicationValidationError) as error:
        st.error(str(error))
    except (DocumentAProcessingError, DocumentBProcessingError) as error:
        st.session_state[REPLACEMENT_ERROR_KEY] = (
            f"{label} could not be activated: {error} Any existing active version remains in use."
        )
        st.rerun()
    except Exception:
        logger.exception(
            "document_a_replacement_processing_failed"
            if is_document_a
            else "document_b_replacement_processing_failed"
        )
        st.session_state[REPLACEMENT_ERROR_KEY] = (
            f"{label} could not be activated. See the private UI log. "
            "Any existing active version remains in use."
        )
        st.rerun()
    else:
        st.session_state[REPLACEMENT_SUCCESS_KEY] = replacement_success_message(asset)
        st.rerun()
