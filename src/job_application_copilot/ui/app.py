"""Minimal Streamlit application entry point."""

import streamlit as st

from job_application_copilot.config import load_settings
from job_application_copilot.services.local_directories import (
    LocalDirectoryError,
    ensure_local_directories,
)


def main() -> None:
    """Render the application scaffold."""
    st.set_page_config(page_title="Job Application Copilot")

    try:
        ensure_local_directories(load_settings())
    except LocalDirectoryError as error:
        st.error(str(error))
        st.stop()

    st.title("Job Application Copilot")
    st.info("The application scaffold is ready.")


if __name__ == "__main__":
    main()
