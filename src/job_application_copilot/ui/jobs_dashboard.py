"""Initial Jobs dashboard table and selection state."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import JobService
from job_application_copilot.ui.job_form import SAVED_MESSAGE_KEY

logger = get_logger(__name__)
JOBS_TABLE_KEY = "jobs_dashboard_table"
SELECTED_JOB_IDS_KEY = "selected_job_ids"
LOAD_ERROR_MESSAGE = "The jobs could not be loaded. See the private UI log for details."
TABLE_COLUMN_ORDER = (
    "company",
    "job_title",
    "location",
    "language",
    "source",
    "job_details",
    "date_added",
    "updated_at",
)


@dataclass(frozen=True, slots=True)
class JobDashboardRow:
    """Stable job identity and display values for one dashboard row."""

    job_id: int
    company: str
    job_title: str
    location: str
    language: str
    source: str
    job_details: str
    date_added: date
    updated_at: datetime

    @classmethod
    def from_job(cls, job: Job) -> "JobDashboardRow":
        """Shape a persisted job for the dashboard."""

        return cls(
            job_id=job.id,
            company=job.company,
            job_title=job.job_title,
            location=job.location.value,
            language=job.language.value,
            source=job.source,
            job_details=f"/job-details?job_id={job.id}",
            date_added=job.date_added,
            updated_at=job.updated_at,
        )

    def display_record(self) -> dict[str, object]:
        """Return only the values rendered in the table."""

        return {
            "company": self.company,
            "job_title": self.job_title,
            "location": self.location,
            "language": self.language,
            "source": self.source,
            "job_details": self.job_details,
            "date_added": self.date_added,
            "updated_at": self.updated_at,
        }


def shape_job_rows(jobs: Iterable[Job]) -> tuple[JobDashboardRow, ...]:
    """Preserve service ordering while shaping dashboard rows."""

    return tuple(JobDashboardRow.from_job(job) for job in jobs)


def selected_job_ids(
    rows: Sequence[JobDashboardRow],
    selected_positions: Iterable[int],
) -> tuple[int, ...]:
    """Map Streamlit's original row positions to stable database IDs."""

    selected_ids: list[int] = []
    for position in selected_positions:
        if position < 0 or position >= len(rows):
            raise ValueError(f"Selected row position {position} is outside the jobs table.")
        selected_ids.append(rows[position].job_id)
    return tuple(selected_ids)


def render_jobs_dashboard(service: JobService) -> None:
    """Load and render the initial Jobs dashboard."""

    st.title("Jobs")
    if saved_message := st.session_state.pop(SAVED_MESSAGE_KEY, None):
        st.success(saved_message)
    st.page_link("pages/add_job.py", label="Add job")

    try:
        rows = shape_job_rows(service.list())
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_load_failed")
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.error(LOAD_ERROR_MESSAGE)
        return

    if not rows:
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.info("No jobs have been added yet.")
        return

    table_state = st.dataframe(
        [row.display_record() for row in rows],
        key=JOBS_TABLE_KEY,
        hide_index=True,
        column_order=TABLE_COLUMN_ORDER,
        column_config={
            "company": st.column_config.TextColumn("Company"),
            "job_title": st.column_config.TextColumn("Job title"),
            "location": st.column_config.TextColumn("Location", width="small"),
            "language": st.column_config.TextColumn("Language", width="small"),
            "source": st.column_config.TextColumn("Source"),
            "job_details": st.column_config.LinkColumn(
                "Job Details",
                display_text="Open",
                width="small",
            ),
            "date_added": st.column_config.DateColumn(
                "Date added",
                format="YYYY-MM-DD",
            ),
            "updated_at": st.column_config.DatetimeColumn(
                "Updated",
                help="UTC",
                format="YYYY-MM-DD HH:mm:ss",
            ),
        },
        on_select="rerun",
        selection_mode="multi-row",
        width="stretch",
    )
    selected_ids = selected_job_ids(rows, table_state.selection.rows)
    st.session_state[SELECTED_JOB_IDS_KEY] = selected_ids
    selected_count = len(selected_ids)
    label = "job" if selected_count == 1 else "jobs"
    st.caption(f"{selected_count} {label} selected.")
