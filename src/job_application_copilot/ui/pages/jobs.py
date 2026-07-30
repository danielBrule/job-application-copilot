"""Jobs dashboard page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.jobs_dashboard import render_jobs_dashboard
from job_application_copilot.ui.dependencies import (
    get_assessment_batch_service,
    get_job_service,
)

settings = load_settings()
render_jobs_dashboard(
    get_job_service(settings.database_path),
    get_assessment_batch_service(settings.database_path),
)
