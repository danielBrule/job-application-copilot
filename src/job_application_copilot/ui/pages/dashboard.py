"""Operational KPI dashboard page."""

from job_application_copilot.config import load_settings
from job_application_copilot.ui.components.dashboard import render_dashboard
from job_application_copilot.ui.dependencies import (
    get_background_run_service,
    get_dashboard_kpi_service,
)

settings = load_settings()
render_dashboard(
    get_dashboard_kpi_service(settings.database_path),
    get_background_run_service(settings.database_path),
)
