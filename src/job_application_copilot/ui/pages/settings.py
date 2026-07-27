"""Prompt-specific Settings page."""

import streamlit as st

from job_application_copilot.config import load_settings
from job_application_copilot.domain import DOCUMENT_A_KEY, DOCUMENT_B_KEY
from job_application_copilot.ui.components.document_b_processing import (
    render_document_b_processing,
)
from job_application_copilot.ui.components.prompt_settings import render_prompt_settings
from job_application_copilot.ui.components.reference_asset_overview import (
    render_reference_asset_overview,
)
from job_application_copilot.ui.components.reference_asset_remote_cleanup import (
    render_reference_asset_remote_cleanup,
)
from job_application_copilot.ui.components.reference_asset_replacement import (
    render_reference_asset_replacements,
)
from job_application_copilot.ui.dependencies import (
    get_document_a_processing_service,
    get_document_b_processing_service,
    get_prompt_service,
    get_reference_asset_overview_service,
    get_reference_asset_remote_cleanup_service,
    get_reference_asset_storage_service,
)

settings = load_settings()
st.title("Settings")
overview = render_reference_asset_overview(get_reference_asset_overview_service(settings))
document_a_overview = (
    next(
        (item for item in overview.required_assets if item.requirement.asset_key == DOCUMENT_A_KEY),
        None,
    )
    if overview is not None
    else None
)
document_b_overview = (
    next(
        (item for item in overview.required_assets if item.requirement.asset_key == DOCUMENT_B_KEY),
        None,
    )
    if overview is not None
    else None
)
document_b_processing_service = get_document_b_processing_service(settings)
render_reference_asset_replacements(
    get_reference_asset_storage_service(settings),
    overview.french_examples if overview is not None else None,
    get_document_a_processing_service(settings),
    document_b_processing_service,
    document_a_exists=(
        document_a_overview is not None and document_a_overview.latest_version is not None
    ),
    document_b_exists=(
        document_b_overview is not None and document_b_overview.latest_version is not None
    ),
)
render_document_b_processing(
    document_b_processing_service,
    document_b_overview,
)
render_reference_asset_remote_cleanup(
    get_reference_asset_remote_cleanup_service(settings),
)
render_prompt_settings(
    get_prompt_service(settings),
    show_page_title=False,
    show_completeness=False,
)
