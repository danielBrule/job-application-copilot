"""Validated Streamlit form for creating jobs."""

import logging
from datetime import date

import streamlit as st
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import CreateJob, Language, Location
from job_application_copilot.observability import get_logger, log_event
from job_application_copilot.services import DuplicateJobUrlError, JobService

logger = get_logger(__name__)
FORM_VERSION_KEY = "add_job_form_version"
SAVED_MESSAGE_KEY = "job_saved_message"
SAVE_ERROR_MESSAGE = "The job could not be saved. See the private UI log for details."
FIELD_LABELS = {
    "company": "Company",
    "job_title": "Job title",
    "location": "Location",
    "language": "Language",
    "source": "Source",
    "job_url": "Job URL",
    "job_description": "Full job description",
    "date_added": "Date added",
    "general_notes": "Notes",
}


class AddJobFormData(BaseModel):
    """Validated values accepted by the add-job UI boundary."""

    company: str = Field(max_length=255)
    job_title: str = Field(max_length=255)
    location: Location
    language: Language
    source: str = Field(max_length=255)
    job_url: str | None = Field(default=None, max_length=2048)
    job_description: str
    date_added: date
    general_notes: str | None = None

    @field_validator("company", "job_title", "source", mode="before")
    @classmethod
    def validate_required_short_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("is required")
        return value

    @field_validator("job_description", mode="before")
    @classmethod
    def validate_job_description(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("is required")
        return value

    @field_validator("job_url", mode="before")
    @classmethod
    def normalize_optional_url(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("general_notes", mode="before")
    @classmethod
    def normalize_optional_notes(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def to_command(self) -> CreateJob:
        """Convert validated UI input into the job-service command."""

        return CreateJob(
            company=self.company,
            job_title=self.job_title,
            location=self.location,
            language=self.language,
            source=self.source,
            job_url=self.job_url,
            job_description=self.job_description,
            date_added=self.date_added,
            general_notes=self.general_notes,
        )


def render_add_job_form(settings: AppSettings, service: JobService) -> None:
    """Render and process the add-job screen."""

    st.title("Add job")
    version = st.session_state.get(FORM_VERSION_KEY, 0)
    key_prefix = f"add_job_{version}"

    with st.form(key=f"{key_prefix}_form"):
        company = st.text_input("Company", key=f"{key_prefix}_company")
        job_title = st.text_input("Job title", key=f"{key_prefix}_job_title")
        location = st.selectbox(
            "Location",
            options=list(Location),
            index=list(Location).index(settings.default_location),
            key=f"{key_prefix}_location",
        )
        language = st.selectbox(
            "Language",
            options=list(Language),
            index=list(Language).index(settings.default_language),
            key=f"{key_prefix}_language",
        )
        source = st.text_input(
            "Source",
            value=settings.default_source,
            key=f"{key_prefix}_source",
        )
        job_url = st.text_input("Job URL", key=f"{key_prefix}_job_url")
        job_description = st.text_area(
            "Full job description",
            height=300,
            key=f"{key_prefix}_job_description",
        )
        date_added = st.date_input(
            "Date added",
            value=date.today(),
            key=f"{key_prefix}_date_added",
        )
        general_notes = st.text_area("Notes", key=f"{key_prefix}_general_notes")

        save_column, save_another_column, cancel_column = st.columns(3)
        with save_column:
            save = st.form_submit_button("Save", type="primary")
        with save_another_column:
            save_and_add_another = st.form_submit_button("Save and add another")
        with cancel_column:
            cancel = st.form_submit_button("Cancel")

    if cancel:
        st.switch_page("pages/jobs.py")
    if not save and not save_and_add_another:
        return

    try:
        form_data = AddJobFormData(
            company=company,
            job_title=job_title,
            location=location,
            language=language,
            source=source,
            job_url=job_url,
            job_description=job_description,
            date_added=date_added,
            general_notes=general_notes,
        )
    except ValidationError as error:
        for message in validation_messages(error):
            st.error(message)
        return

    try:
        job = service.create(form_data.to_command())
    except DuplicateJobUrlError as error:
        st.error(f"Another job already uses this exact URL (job {error.existing_job_id}).")
        return
    except SQLAlchemyError:
        logger.exception("job_create_failed")
        st.error(SAVE_ERROR_MESSAGE)
        return

    log_event(logger, logging.INFO, "job_created", job_id=job.id)
    st.session_state[SAVED_MESSAGE_KEY] = f"Saved {job.company} — {job.job_title}."
    if save_and_add_another:
        st.session_state[FORM_VERSION_KEY] = version + 1
        st.rerun()
    st.switch_page("pages/jobs.py")


def validation_messages(error: ValidationError) -> list[str]:
    """Return concise field-specific messages for form validation failures."""

    messages: list[str] = []
    for detail in error.errors():
        field_name = str(detail["loc"][0])
        label = FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())
        if detail["type"] == "value_error":
            messages.append(f"{label} is required.")
        else:
            messages.append(f"{label}: {detail['msg']}.")
    return messages
