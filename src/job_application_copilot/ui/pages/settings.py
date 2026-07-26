"""Prompt-specific Settings page."""

import streamlit as st

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.prompt_settings import render_prompt_settings
from job_application_copilot.ui.components.reference_asset_overview import (
    render_reference_asset_overview,
)
from job_application_copilot.ui.components.reference_asset_replacement import (
    render_reference_asset_replacements,
)
from job_application_copilot.ui.dependencies import (
    get_prompt_service,
    get_reference_asset_overview_service,
    get_reference_asset_storage_service,
)

settings = load_settings()
st.title("Settings")
overview = render_reference_asset_overview(get_reference_asset_overview_service(settings))
render_reference_asset_replacements(
    get_reference_asset_storage_service(settings),
    overview.french_examples if overview is not None else None,
)
render_prompt_settings(
    get_prompt_service(settings),
    show_page_title=False,
    show_completeness=False,
)
