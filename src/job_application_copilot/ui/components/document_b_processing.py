"""Settings action for synchronous Document B processing and activation."""

from collections.abc import Callable
from typing import Protocol

import streamlit as st

from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    RequiredReferenceAssetOverview,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services import DocumentBProcessingError
from job_application_copilot.services.document_b_progress import DocumentBProcessingProgress

logger = get_logger(__name__)
DOCUMENT_B_PROCESSING_SUCCESS_KEY = "document_b_processing_success"
DOCUMENT_B_PROCESSING_BUTTON_KEY = "process_and_activate_document_b"
DOCUMENT_B_PROCESSING_IN_PROGRESS_KEY = "document_b_processing_in_progress"
DOCUMENT_B_PROCESSING_PROGRESS_KEY = "document_b_processing_progress"
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

    def process(
        self,
        version: int,
        *,
        progress: Callable[[DocumentBProcessingProgress], None] | None = None,
    ) -> ReferenceAsset:
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
    in_progress = bool(st.session_state.get(DOCUMENT_B_PROCESSING_IN_PROGRESS_KEY, False))
    if in_progress:
        st.info("Document B processing is already running in this browser session.")
        _render_saved_progress(st.session_state.get(DOCUMENT_B_PROCESSING_PROGRESS_KEY))
    if not st.button(
        "Process and activate",
        key=DOCUMENT_B_PROCESSING_BUTTON_KEY,
        type="primary",
        disabled=in_progress,
    ):
        return

    st.session_state[DOCUMENT_B_PROCESSING_IN_PROGRESS_KEY] = True
    st.session_state[DOCUMENT_B_PROCESSING_PROGRESS_KEY] = DocumentBProcessingProgress(
        stage="starting",
        message=f"Starting Document B v{candidate.version} processing.",
    )
    progress_bar = st.progress(0, text="Starting Document B processing...")
    status = st.empty()

    def show_progress(update: DocumentBProcessingProgress) -> None:
        st.session_state[DOCUMENT_B_PROCESSING_PROGRESS_KEY] = update
        if update.completed_sections is not None and update.total_sections:
            percentage = int((update.completed_sections / update.total_sections) * 100)
            progress_bar.progress(min(percentage, 100), text=update.message)
        else:
            progress_bar.progress(0, text=update.message)
        status.caption(update.message)

    try:
        activated = service.process(candidate.version, progress=show_progress)
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
    finally:
        st.session_state[DOCUMENT_B_PROCESSING_IN_PROGRESS_KEY] = False


def _render_saved_progress(value: object) -> None:
    """Show the latest session-scoped progress after navigation back to Settings."""

    if not isinstance(value, DocumentBProcessingProgress):
        return
    if value.completed_sections is not None and value.total_sections:
        percentage = int((value.completed_sections / value.total_sections) * 100)
        st.progress(min(percentage, 100), text=value.message)
    else:
        st.progress(0, text=value.message)
    st.caption(value.message)
