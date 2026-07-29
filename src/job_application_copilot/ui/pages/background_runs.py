"""Background Runs page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.background_runs import render_background_runs
from job_application_copilot.ui.dependencies import get_background_run_service

settings = load_settings()
render_background_runs(get_background_run_service(settings.database_path))
