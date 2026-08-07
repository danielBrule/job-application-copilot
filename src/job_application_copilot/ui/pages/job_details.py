"""Job Details page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.job_details import render_job_details
from job_application_copilot.ui.dependencies import (
    get_cv_file_opener,
    get_cv_generation_batch_service,
    get_cv_service,
    get_cv_upload_service,
    get_job_service,
)

settings = load_settings()
render_job_details(
    get_job_service(settings.database_path),
    get_cv_service(settings),
    get_cv_upload_service(settings),
    get_cv_file_opener(settings),
    get_cv_generation_batch_service(settings.database_path),
)
