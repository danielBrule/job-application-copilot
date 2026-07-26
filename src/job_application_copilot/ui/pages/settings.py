"""Prompt-specific Settings page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.dependencies import get_prompt_service
from job_application_copilot.ui.prompt_settings import render_prompt_settings

settings = load_settings()
render_prompt_settings(get_prompt_service(settings))
