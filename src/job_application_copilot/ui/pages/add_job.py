"""Add-job page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.dependencies import get_job_service
from job_application_copilot.ui.job_form import render_add_job_form

settings = load_settings()
render_add_job_form(settings, get_job_service(settings.database_path))
