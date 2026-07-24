"""Streamlit application startup and navigation shell."""

import logging
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from job_application_copilot.config import load_settings
from job_application_copilot.observability import (
    LogComponent,
    LoggingConfigurationError,
    configure_logging,
    get_logger,
    log_event,
)
from job_application_copilot.services.database_bootstrap import (
    DatabaseHealthError,
    DatabaseMigrationError,
    initialize_database,
)
from job_application_copilot.services.local_directories import (
    LocalDirectoryError,
    ensure_local_directories,
)

logger = get_logger("job_application_copilot.ui.app")
PAGES_DIRECTORY = Path(__file__).parent / "pages"
UNEXPECTED_ERROR_MESSAGE = (
    "An unexpected application error occurred. See the private UI log for details."
)


def main() -> None:
    """Initialize the application and render its navigation shell."""
    st.set_page_config(page_title="Job Application Copilot", layout="wide")

    try:
        settings = load_settings()
        ensure_local_directories(settings)
        configure_logging(settings, LogComponent.UI)
        initialize_database(settings.database_path)
    except (
        DatabaseHealthError,
        DatabaseMigrationError,
        LocalDirectoryError,
        LoggingConfigurationError,
        ValidationError,
    ) as error:
        st.error(str(error))
        st.stop()

    log_event(logger, logging.INFO, "application_started")
    selected_page = st.navigation(
        [
            st.Page(
                PAGES_DIRECTORY / "jobs.py",
                title="Jobs",
                url_path="jobs",
                default=True,
            ),
            st.Page(
                PAGES_DIRECTORY / "background_runs.py",
                title="Background Runs",
                url_path="background-runs",
            ),
            st.Page(
                PAGES_DIRECTORY / "settings.py",
                title="Settings",
                url_path="settings",
            ),
        ]
    )
    try:
        selected_page.run()
    except Exception as error:
        logger.exception(
            "unexpected_page_error exception_type=%s",
            type(error).__name__,
        )
        st.error(UNEXPECTED_ERROR_MESSAGE)
        st.stop()


if __name__ == "__main__":
    main()
