"""Process-local dependencies shared by Streamlit pages."""

from pathlib import Path

import streamlit as st

from job_application_copilot.repositories import Database, create_database
from job_application_copilot.services import JobService


def _dispose_database(database: Database) -> None:
    database.dispose()


@st.cache_resource(show_spinner=False, on_release=_dispose_database)
def get_database(database_path: Path) -> Database:
    """Return one database facade per configured path for this UI process."""

    return create_database(database_path)


def get_job_service(database_path: Path) -> JobService:
    """Build a job service using the UI process's shared database facade."""

    return JobService(get_database(database_path))
