"""Settings controls for reviewing and maintaining Document B routing YAML."""

from typing import Protocol

import streamlit as st

from job_application_copilot.domain import RequiredReferenceAssetOverview
from job_application_copilot.services import (
    DocumentBRoutingConfigurationError,
    DocumentBRoutingConfigurationStorageError,
)
from job_application_copilot.services.document_b_sections import DocumentBSectionRecord

ROUTING_TEXT_KEY = "document_b_routing_yaml"
ROUTING_HEADINGS_KEY = "document_b_routing_headings"


class DocumentBRoutingConfigurationEditor(Protocol):
    """Boundary between Settings and local routing authoring operations."""

    def load_text(self) -> str: ...

    def headings(self, version: int) -> tuple[DocumentBSectionRecord, ...]: ...

    def validate_and_save(self, version: int, content: str) -> None: ...


def render_document_b_routing_configuration(
    service: DocumentBRoutingConfigurationEditor,
    overview: RequiredReferenceAssetOverview | None,
) -> None:
    """Allow a content owner to validate paths before Document B processing."""

    candidate = overview.latest_version if overview is not None else None
    if candidate is None:
        return
    st.subheader("Document B routing")
    st.caption(
        f"Review the exact headings in Document B v{candidate.version}, then validate and save "
        "its private routing YAML before processing. This step never calls OpenAI."
    )
    try:
        current_text = service.load_text()
    except DocumentBRoutingConfigurationStorageError as error:
        st.error(str(error))
        return

    with st.expander(f"Review routing for Document B v{candidate.version}"):
        if st.button("Show exact heading catalogue", key="show_document_b_heading_catalogue"):
            try:
                st.session_state[ROUTING_HEADINGS_KEY] = service.headings(candidate.version)
            except DocumentBRoutingConfigurationError as error:
                st.error(str(error))
        headings = st.session_state.get(ROUTING_HEADINGS_KEY)
        if isinstance(headings, tuple) and all(
            isinstance(section, DocumentBSectionRecord) for section in headings
        ):
            st.code(_heading_catalogue(headings), language=None)

        with st.form("document_b_routing_configuration"):
            content = st.text_area(
                "Document B routing YAML",
                value=current_text,
                key=ROUTING_TEXT_KEY,
                height=420,
            )
            submitted = st.form_submit_button("Validate and save routing")
        if submitted:
            try:
                service.validate_and_save(candidate.version, content)
            except (
                DocumentBRoutingConfigurationError,
                DocumentBRoutingConfigurationStorageError,
            ) as error:
                st.error(str(error))
            else:
                st.success(
                    f"Routing YAML is valid for Document B v{candidate.version} and was saved. "
                    "Select Process and activate to finish activation."
                )


def _heading_catalogue(headings: tuple[DocumentBSectionRecord, ...]) -> str:
    return "\n".join(
        f"{'  ' * max(section.heading_level - 1, 0)}- {section.heading_title}"
        for section in headings
        if section.heading_level > 0
    )
