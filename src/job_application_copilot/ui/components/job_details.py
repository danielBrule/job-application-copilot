"""Job Details page-content component."""

import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.observability import get_logger, log_event
from job_application_copilot.services import JobService
from job_application_copilot.ui.components.job_form import render_edit_job_form

logger = get_logger(__name__)
LOAD_ERROR_MESSAGE = "The job could not be loaded. See the private UI log for details."


def parse_job_id(value: str | None) -> int:
    """Parse a positive job identifier from a query parameter."""

    if value is None:
        raise ValueError("A job ID is required.")
    try:
        job_id = int(value)
    except ValueError as error:
        raise ValueError("The job ID must be a positive integer.") from error
    if job_id <= 0:
        raise ValueError("The job ID must be a positive integer.")
    return job_id


def render_job_details(service: JobService) -> None:
    """Load and render the editable Job Details page."""

    st.title("Job details")
    try:
        job_id = parse_job_id(st.query_params.get("job_id"))
    except ValueError as error:
        st.error(str(error))
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return

    try:
        job = service.get(job_id)
    except SQLAlchemyError:
        logger.exception("job_load_failed job_id=%s", job_id)
        st.error(LOAD_ERROR_MESSAGE)
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return

    if job is None:
        log_event(logger, logging.WARNING, "job_not_found", job_id=job_id)
        st.error(f"Job {job_id} does not exist.")
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return

    render_edit_job_form(job, service)
