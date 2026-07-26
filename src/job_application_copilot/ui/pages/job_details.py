"""Job Details page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.job_details import render_job_details
from job_application_copilot.ui.dependencies import get_job_service

settings = load_settings()
render_job_details(get_job_service(settings.database_path))
