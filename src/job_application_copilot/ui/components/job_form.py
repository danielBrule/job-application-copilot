"""Shared validation and Streamlit job-form components."""

import logging
from dataclasses import dataclass
from datetime import date

import streamlit as st
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    CreateJob,
    Language,
    Location,
    Relevance,
    UpdateJob,
)
from job_application_copilot.observability import get_logger, log_event
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import (
    DuplicateJobUrlError,
    JobNotFoundError,
    JobService,
)

logger = get_logger(__name__)
ADD_FORM_VERSION_KEY = "add_job_form_version"
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


@dataclass(frozen=True, slots=True)
class JobFormInitialValues:
    """Values displayed before a job form is submitted."""

    company: str
    job_title: str
    location: Location
    language: Language
    source: str
    job_url: str
    job_description: str
    date_added: date
    general_notes: str
    relevance_override: Relevance | None

    @classmethod
    def for_add(cls, settings: AppSettings) -> "JobFormInitialValues":
        """Build configured defaults for a new job."""

        return cls(
            company="",
            job_title="",
            location=settings.default_location,
            language=settings.default_language,
            source=settings.default_source,
            job_url="",
            job_description="",
            date_added=date.today(),
            general_notes="",
            relevance_override=None,
        )

    @classmethod
    def from_job(cls, job: Job) -> "JobFormInitialValues":
        """Build edit defaults from a persisted job."""

        return cls(
            company=job.company,
            job_title=job.job_title,
            location=job.location,
            language=job.language,
            source=job.source,
            job_url=job.job_url or "",
            job_description=job.job_description,
            date_added=job.date_added,
            general_notes=job.general_notes or "",
            relevance_override=job.relevance_override,
        )


class JobFormData(BaseModel):
    """Validated values accepted by the add and edit UI boundary."""

    company: str = Field(max_length=255)
    job_title: str = Field(max_length=255)
    location: Location
    language: Language
    source: str = Field(max_length=255)
    job_url: str | None = Field(default=None, max_length=2048)
    job_description: str
    date_added: date
    general_notes: str | None = None
    relevance_override: Relevance | None = None

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

    def to_create_command(self) -> CreateJob:
        """Convert validated UI input into a create command."""

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
            relevance_override=self.relevance_override,
        )

    def to_update_command(self, current_job: Job) -> UpdateJob:
        """Replace form-owned fields while preserving other job state."""

        return UpdateJob(
            company=self.company,
            job_title=self.job_title,
            location=self.location,
            language=self.language,
            source=self.source,
            job_url=self.job_url,
            job_description=self.job_description,
            date_added=self.date_added,
            general_notes=self.general_notes,
            relevance_override=self.relevance_override,
            user_decision=current_job.user_decision,
            application_status=current_job.application_status,
            application_date=current_job.application_date,
            next_action=current_job.next_action,
            next_action_date=current_job.next_action_date,
            salary_expectation=current_job.salary_expectation,
            closure_reason=current_job.closure_reason,
        )


def render_add_job_form(settings: AppSettings, service: JobService) -> None:
    """Render and process the add-job screen."""

    st.title("Add job")
    version = st.session_state.get(ADD_FORM_VERSION_KEY, 0)
    key_prefix = f"add_job_{version}"
    values, save, save_and_add_another, cancel = _render_form(
        initial=JobFormInitialValues.for_add(settings),
        key_prefix=key_prefix,
        include_save_and_add_another=True,
    )

    if cancel:
        st.switch_page("pages/jobs.py")
    if not save and not save_and_add_another:
        return

    form_data = _validate_form(values)
    if form_data is None:
        return

    try:
        job = service.create(form_data.to_create_command())
    except DuplicateJobUrlError as error:
        _show_duplicate_url_error(error)
        return
    except SQLAlchemyError:
        logger.exception("job_create_failed")
        st.error(SAVE_ERROR_MESSAGE)
        return

    log_event(logger, logging.INFO, "job_created", job_id=job.id)
    _set_saved_message(job)
    if save_and_add_another:
        st.session_state[ADD_FORM_VERSION_KEY] = version + 1
        st.rerun()
    st.switch_page("pages/jobs.py")


def render_edit_job_form(job: Job, service: JobService) -> None:
    """Render and process the editable Job Details section."""

    st.subheader("Edit job")
    values, save, _, cancel = _render_form(
        initial=JobFormInitialValues.from_job(job),
        key_prefix=f"edit_job_{job.id}",
        include_save_and_add_another=False,
    )

    if cancel:
        st.switch_page("pages/jobs.py")
    if not save:
        return

    form_data = _validate_form(values)
    if form_data is None:
        return

    try:
        updated_job = service.update(job.id, form_data.to_update_command(job))
    except DuplicateJobUrlError as error:
        _show_duplicate_url_error(error)
        return
    except JobNotFoundError:
        st.error(f"Job {job.id} no longer exists.")
        st.page_link("pages/jobs.py", label="Back to Jobs")
        return
    except SQLAlchemyError:
        logger.exception("job_update_failed job_id=%s", job.id)
        st.error(SAVE_ERROR_MESSAGE)
        return

    log_event(logger, logging.INFO, "job_updated", job_id=updated_job.id)
    _set_saved_message(updated_job)
    st.switch_page("pages/jobs.py")


def _render_form(
    initial: JobFormInitialValues,
    key_prefix: str,
    include_save_and_add_another: bool,
) -> tuple[dict[str, object], bool, bool, bool]:
    with st.form(key=f"{key_prefix}_form"):
        values: dict[str, object] = {
            "company": st.text_input(
                "Company",
                value=initial.company,
                key=f"{key_prefix}_company",
            ),
            "job_title": st.text_input(
                "Job title",
                value=initial.job_title,
                key=f"{key_prefix}_job_title",
            ),
            "location": st.selectbox(
                "Location",
                options=list(Location),
                index=list(Location).index(initial.location),
                key=f"{key_prefix}_location",
            ),
            "language": st.selectbox(
                "Language",
                options=list(Language),
                index=list(Language).index(initial.language),
                key=f"{key_prefix}_language",
            ),
            "relevance_override": st.selectbox(
                "Relevance override",
                options=[None, *Relevance],
                index=[None, *Relevance].index(initial.relevance_override),
                format_func=_relevance_override_label,
                help=(
                    "Your value takes precedence over assessment relevance. "
                    "Choose 'Use assessment relevance' to clear the override."
                ),
                key=f"{key_prefix}_relevance_override",
            ),
            "source": st.text_input(
                "Source",
                value=initial.source,
                key=f"{key_prefix}_source",
            ),
            "job_url": st.text_input(
                "Job URL",
                value=initial.job_url,
                key=f"{key_prefix}_job_url",
            ),
            "job_description": st.text_area(
                "Full job description",
                value=initial.job_description,
                height=300,
                key=f"{key_prefix}_job_description",
            ),
            "date_added": st.date_input(
                "Date added",
                value=initial.date_added,
                key=f"{key_prefix}_date_added",
            ),
            "general_notes": st.text_area(
                "Notes",
                value=initial.general_notes,
                key=f"{key_prefix}_general_notes",
            ),
        }

        save_column, secondary_column, cancel_column = st.columns(3)
        with save_column:
            save = st.form_submit_button("Save", type="primary")
        with secondary_column:
            save_and_add_another = (
                st.form_submit_button("Save and add another")
                if include_save_and_add_another
                else False
            )
        with cancel_column:
            cancel = st.form_submit_button("Cancel")

    return values, save, save_and_add_another, cancel


def _relevance_override_label(value: object) -> str:
    if value is None:
        return "Use assessment relevance"
    if isinstance(value, Relevance):
        return value.value.title()
    return str(value)


def _validate_form(values: dict[str, object]) -> JobFormData | None:
    try:
        return JobFormData.model_validate(values)
    except ValidationError as error:
        for message in validation_messages(error):
            st.error(message)
        return None


def _show_duplicate_url_error(error: DuplicateJobUrlError) -> None:
    st.error(f"Another job already uses this exact URL (job {error.existing_job_id}).")


def _set_saved_message(job: Job) -> None:
    st.session_state[SAVED_MESSAGE_KEY] = f"Saved {job.company} — {job.job_title}."


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
