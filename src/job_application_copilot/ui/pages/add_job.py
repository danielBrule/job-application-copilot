"""Add-job page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.job_form import render_add_job_form
from job_application_copilot.ui.dependencies import get_job_service

settings = load_settings()
render_add_job_form(settings, get_job_service(settings.database_path))
