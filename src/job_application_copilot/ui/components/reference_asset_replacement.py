"""Settings composition for canonical and locally validated reference assets."""

import streamlit as st

from job_application_copilot.domain import (
    DOCUMENT_A_KEY,
    DOCUMENT_B_KEY,
    REQUIRED_REFERENCE_ASSETS,
    FrenchReferenceExamplesOverview,
)
from job_application_copilot.services import ReferenceAssetStorageService
from job_application_copilot.ui.components.local_reference_asset_replacement import (
    render_french_example_form,
    render_local_reference_asset_form,
)
from job_application_copilot.ui.components.reference_asset_replacement_state import (
    REPLACEMENT_ERROR_KEY,
    REPLACEMENT_SUCCESS_KEY,
)
from job_application_copilot.ui.components.reference_document_replacement import (
    DocumentAReplacementProcessor,
    DocumentBReplacementProcessor,
    render_reference_document_form,
)


def render_reference_asset_replacements(
    service: ReferenceAssetStorageService,
    french_examples: FrenchReferenceExamplesOverview | None,
    document_a_processor: DocumentAReplacementProcessor,
    document_b_processor: DocumentBReplacementProcessor,
    *,
    document_a_exists: bool,
    document_b_exists: bool,
) -> None:
    """Render canonical replacement controls and dynamic French-example input."""

    st.subheader("Local DOCX uploads")
    st.caption(
        "Templates and French examples become active after local validation. "
        "Documents A and B are stored, processed with OpenAI and activated in one explicit "
        "workflow. "
        "Earlier local versions are retained."
    )
    if message := st.session_state.pop(REPLACEMENT_SUCCESS_KEY, None):
        st.success(message)
    if message := st.session_state.pop(REPLACEMENT_ERROR_KEY, None):
        st.error(message)

    for requirement in REQUIRED_REFERENCE_ASSETS:
        if requirement.asset_key == DOCUMENT_A_KEY:
            render_reference_document_form(
                requirement,
                document_a_processor,
                asset_exists=document_a_exists,
            )
        elif requirement.asset_key == DOCUMENT_B_KEY:
            render_reference_document_form(
                requirement,
                document_b_processor,
                asset_exists=document_b_exists,
            )
        else:
            render_local_reference_asset_form(service, requirement)

    render_french_example_form(service, french_examples)
