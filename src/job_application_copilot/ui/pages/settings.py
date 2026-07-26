"""Prompt-specific Settings page."""

import streamlit as st

from job_application_copilot.config import load_settings
from job_application_copilot.ui.dependencies import (
    get_prompt_service,
    get_reference_asset_overview_service,
)
from job_application_copilot.ui.prompt_settings import render_prompt_settings
from job_application_copilot.ui.reference_asset_overview import (
    render_reference_asset_overview,
)

settings = load_settings()
st.title("Settings")
render_reference_asset_overview(get_reference_asset_overview_service(settings))
render_prompt_settings(
    get_prompt_service(settings),
    show_page_title=False,
    show_completeness=False,
)
