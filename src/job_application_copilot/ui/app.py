"""Minimal Streamlit application entry point."""

import logging

import streamlit as st

from job_application_copilot.config import load_settings
from job_application_copilot.observability import (
    LogComponent,
    LoggingConfigurationError,
    configure_logging,
    get_logger,
    log_event,
)
from job_application_copilot.services.local_directories import (
    LocalDirectoryError,
    ensure_local_directories,
)

logger = get_logger("job_application_copilot.ui.app")


def main() -> None:
    """Render the application scaffold."""
    st.set_page_config(page_title="Job Application Copilot")

    try:
        settings = load_settings()
        ensure_local_directories(settings)
        configure_logging(settings, LogComponent.UI)
    except (LocalDirectoryError, LoggingConfigurationError) as error:
        st.error(str(error))
        st.stop()

    log_event(logger, logging.INFO, "application_started")
    st.title("Job Application Copilot")
    st.info("The application scaffold is ready.")


if __name__ == "__main__":
    main()
