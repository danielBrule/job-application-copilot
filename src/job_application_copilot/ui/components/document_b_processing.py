"""Settings action for synchronous Document B processing and activation."""

from typing import Protocol

import streamlit as st

from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    RequiredReferenceAssetOverview,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services import DocumentBProcessingError

logger = get_logger(__name__)
DOCUMENT_B_PROCESSING_SUCCESS_KEY = "document_b_processing_success"
DOCUMENT_B_PROCESSING_BUTTON_KEY = "process_and_activate_document_b"
DOCUMENT_B_PROCESSING_ERROR_MESSAGE = "Document B could not be processed. See the private UI log."
PROCESSABLE_STATUSES = frozenset(
    {
        ReferenceAssetProcessingStatus.PENDING,
        ReferenceAssetProcessingStatus.PROCESSING,
        ReferenceAssetProcessingStatus.FAILED,
    }
)


class DocumentBProcessor(Protocol):
    """Boundary between the Settings component and processing workflow."""

    def process(self, version: int) -> ReferenceAsset:
        """Process and activate one retained Document B version."""


def render_document_b_processing(
    service: DocumentBProcessor,
    overview: RequiredReferenceAssetOverview | None,
) -> None:
    """Render processing feedback and an action for the latest eligible candidate."""

    if message := st.session_state.pop(DOCUMENT_B_PROCESSING_SUCCESS_KEY, None):
        st.success(message)

    candidate = overview.latest_version if overview is not None else None
    if (
        candidate is None
        or candidate.is_active
        or candidate.processing_status not in PROCESSABLE_STATUSES
    ):
        return

    st.subheader("Document B processing")
    st.caption(
        f"Document B v{candidate.version} is {candidate.processing_status.value} and not active. "
        "Processing uploads it to OpenAI when needed, validates its vector store, and only then "
        "replaces the active version."
    )
    if not st.button(
        "Process and activate",
        key=DOCUMENT_B_PROCESSING_BUTTON_KEY,
        type="primary",
    ):
        return

    try:
        with st.spinner(f"Processing Document B v{candidate.version} with OpenAI..."):
            activated = service.process(candidate.version)
    except DocumentBProcessingError as error:
        logger.exception(
            "document_b_processing_failed version=%s",
            candidate.version,
        )
        st.error(f"Document B processing failed: {error}")
    except Exception:
        logger.exception(
            "document_b_processing_unexpected_failure version=%s",
            candidate.version,
        )
        st.error(DOCUMENT_B_PROCESSING_ERROR_MESSAGE)
    else:
        st.session_state[DOCUMENT_B_PROCESSING_SUCCESS_KEY] = (
            f"Document B version {activated.version} is active and READY."
        )
        st.rerun()
