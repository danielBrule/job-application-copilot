"""Jobs dashboard page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.dependencies import get_job_service
from job_application_copilot.ui.jobs_dashboard import render_jobs_dashboard

settings = load_settings()
render_jobs_dashboard(get_job_service(settings.database_path))
