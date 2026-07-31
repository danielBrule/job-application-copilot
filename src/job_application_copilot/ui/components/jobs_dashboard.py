"""Jobs dashboard table component and selection state."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.domain import CvSelectionStatus, UserDecision
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.job_repository import JobNotFoundError
from job_application_copilot.repositories.models import Job
from job_application_copilot.services import (
    AssessmentBatchService,
    CvSelectionResult,
    CvSelectionService,
    CvSelectionSkipReason,
    JobService,
)
from job_application_copilot.services.job_service import JobAssessmentSummary
from job_application_copilot.ui.components.job_filters import (
    available_sources,
    has_active_filters,
    render_job_filters,
)
from job_application_copilot.ui.components.job_form import SAVED_MESSAGE_KEY

logger = get_logger(__name__)
JOBS_TABLE_KEY = "jobs_dashboard_table"
SELECTED_JOB_IDS_KEY = "selected_job_ids"
DELETE_CONFIRMATION_IDS_KEY = "delete_confirmation_job_ids"
DELETE_CONFIRMATION_KEY = "confirm_delete_selected_jobs"
DELETE_SUCCESS_KEY = "delete_selected_jobs_success"
ASSESSMENT_CONFIRMATION_IDS_KEY = "assessment_confirmation_job_ids"
ASSESSMENT_CONFIRMATION_KEY = "confirm_assess_selected_jobs"
ASSESSMENT_SUCCESS_KEY = "assess_selected_jobs_success"
REASSESSMENT_CONFIRMATION_IDS_KEY = "reassessment_confirmation_job_ids"
REASSESSMENT_CONFIRMATION_KEY = "confirm_reassess_selected_jobs"
REASSESSMENT_SUCCESS_KEY = "reassess_selected_jobs_success"
CV_SELECTION_CONFIRMATION_IDS_KEY = "cv_selection_confirmation_job_ids"
CV_SELECTION_CONFIRMATION_KEY = "confirm_select_for_cv_generation"
CV_SELECTION_SUCCESS_KEY = "select_for_cv_generation_success"
CLEAR_TABLE_SELECTION_ON_RERUN_KEY = "clear_jobs_dashboard_table_selection_on_rerun"
LOAD_ERROR_MESSAGE = "The jobs could not be loaded. See the private UI log for details."
TABLE_COLUMN_ORDER = (
    "company",
    "job_title",
    "job_url",
    "location",
    "language",
    "source",
    "date_added",
    "assessment_status",
    "recommendation",
    "fit_score",
    "interview_probability",
    "user_decision",
    "selected_cv_lane",
    "cv_selection_status",
    "cv_status",
    "open_cv",
    "application_status",
    "next_action",
    "updated_at",
)


@dataclass(frozen=True, slots=True)
class JobDashboardRow:
    """Stable job identity and display values for one dashboard row."""

    job_id: int
    company: str
    job_title: str
    job_url: str | None
    location: str
    language: str
    source: str
    date_added: date
    updated_at: datetime
    assessment_status: str
    recommendation: str | None
    fit_score: int | None
    interview_probability_low: int | None
    interview_probability_high: int | None
    user_decision: str
    selected_cv_lane: str | None
    cv_selection_status: str
    application_status: str | None
    next_action: str | None

    @classmethod
    def from_job(
        cls,
        job: Job,
        *,
        assessment: JobAssessmentSummary | None = None,
    ) -> "JobDashboardRow":
        """Shape a persisted job for the dashboard."""

        return cls(
            job_id=job.id,
            company=job.company,
            job_title=job.job_title,
            job_url=job.job_url,
            location=job.location.value,
            language=job.language.value,
            source=job.source,
            date_added=job.date_added,
            updated_at=job.updated_at,
            assessment_status=assessment.status.value.title()
            if assessment and assessment.status
            else "Not assessed",
            recommendation=assessment.decision if assessment else None,
            fit_score=assessment.fit_score if assessment else None,
            interview_probability_low=assessment.interview_probability_low if assessment else None,
            interview_probability_high=assessment.interview_probability_high
            if assessment
            else None,
            user_decision=_user_decision_display(job.user_decision),
            selected_cv_lane=assessment.selected_cv_lane if assessment else None,
            cv_selection_status=(
                "Selected for CV generation"
                if job.cv_selection_status is CvSelectionStatus.SELECTED
                else "Not selected"
            ),
            application_status=job.application_status,
            next_action=job.next_action,
        )

    def display_record(self) -> dict[str, object]:
        """Return only the values rendered in the table."""

        return {
            "company": self.company,
            "job_title": self.job_title,
            "job_url": self.job_url,
            "location": self.location,
            "language": self.language,
            "source": self.source,
            "date_added": self.date_added,
            "assessment_status": self.assessment_status,
            "recommendation": self.recommendation or "—",
            "fit_score": self.fit_score,
            "interview_probability": self._interview_probability_display(),
            "user_decision": self.user_decision,
            "selected_cv_lane": self.selected_cv_lane or "—",
            "cv_selection_status": self.cv_selection_status,
            "cv_status": "Not available yet",
            "open_cv": "Unavailable",
            "application_status": self.application_status or "—",
            "next_action": self.next_action or "—",
            "updated_at": self.updated_at,
        }

    def _interview_probability_display(self) -> str:
        if self.interview_probability_low is None or self.interview_probability_high is None:
            return "—"
        average = (self.interview_probability_low + self.interview_probability_high) / 2
        return f"{average:g} / 10"


def _user_decision_display(decision: UserDecision | None) -> str:
    """Return the dashboard label for the persisted human decision."""

    if decision is None:
        return "Undecided"
    labels = {
        UserDecision.UNDECIDED: "Undecided",
        UserDecision.PURSUE: "Pursue",
        UserDecision.DO_NOT_PURSUE: "Do not pursue",
    }
    return labels[decision]


def shape_job_rows(
    jobs: Iterable[Job],
    assessment_summaries: dict[int, JobAssessmentSummary] | None = None,
) -> tuple[JobDashboardRow, ...]:
    """Preserve service ordering while shaping dashboard rows."""

    summaries = assessment_summaries or {}
    return tuple(JobDashboardRow.from_job(job, assessment=summaries.get(job.id)) for job in jobs)


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


def render_jobs_dashboard(
    service: JobService,
    assessment_batch_service: AssessmentBatchService,
    cv_selection_service: CvSelectionService,
) -> None:
    """Load and render the initial Jobs dashboard."""

    st.title("Jobs")
    if saved_message := st.session_state.pop(SAVED_MESSAGE_KEY, None):
        st.success(saved_message)
    if deleted_message := st.session_state.pop(DELETE_SUCCESS_KEY, None):
        st.success(deleted_message)
    if assessment_message := st.session_state.pop(ASSESSMENT_SUCCESS_KEY, None):
        st.success(assessment_message)
    if reassessment_message := st.session_state.pop(REASSESSMENT_SUCCESS_KEY, None):
        st.success(reassessment_message)
    if cv_selection_message := st.session_state.pop(CV_SELECTION_SUCCESS_KEY, None):
        st.success(cv_selection_message)
    try:
        all_jobs = service.list()
        first_review_job_id = service.first_assessment_review_job_id()
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_load_failed")
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.error(LOAD_ERROR_MESSAGE)
        return

    if not all_jobs:
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.info("No jobs have been added yet.")
        return

    add_job_column, review_column, _ = st.columns((1, 1, 4))
    with add_job_column:
        if st.button("Add job", key="add_job", type="primary"):
            st.switch_page("pages/add_job.py")
    if first_review_job_id is not None:
        with review_column:
            st.page_link(
                "pages/job_details.py",
                label="Review assessed jobs",
                query_params={"job_id": str(first_review_job_id)},
            )

    filters = render_job_filters(
        available_sources(all_jobs),
        clear_dashboard_selection,
    )
    try:
        jobs = service.list(filters) if has_active_filters(filters) else all_jobs
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_filter_failed")
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.error(LOAD_ERROR_MESSAGE)
        return

    try:
        assessment_summaries = service.assessment_summaries(tuple(jobs))
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_assessment_staleness_load_failed")
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.error(LOAD_ERROR_MESSAGE)
        return

    rows = shape_job_rows(jobs, assessment_summaries)
    if not rows:
        st.session_state[SELECTED_JOB_IDS_KEY] = ()
        st.info("No jobs match the current filters.")
        return

    _clear_table_selection_if_requested()
    table_state = st.dataframe(
        [row.display_record() for row in rows],
        key=JOBS_TABLE_KEY,
        hide_index=True,
        column_order=TABLE_COLUMN_ORDER,
        column_config={
            "company": st.column_config.TextColumn("Company"),
            "job_title": st.column_config.TextColumn("Job title"),
            "job_url": st.column_config.LinkColumn(
                "Job URL",
                display_text="Open posting",
                width="small",
            ),
            "location": st.column_config.TextColumn("Location", width="small"),
            "language": st.column_config.TextColumn("Language", width="small"),
            "source": st.column_config.TextColumn("Source"),
            "date_added": st.column_config.DateColumn(
                "Date added",
                format="YYYY-MM-DD",
            ),
            "assessment_status": st.column_config.TextColumn("Assessment status", width="small"),
            "recommendation": st.column_config.TextColumn("Model decision", width="small"),
            "fit_score": st.column_config.NumberColumn(
                "Fit score", format="%d / 10", width="small"
            ),
            "interview_probability": st.column_config.TextColumn(
                "Interview probability",
                width="small",
            ),
            "user_decision": st.column_config.TextColumn("User decision", width="small"),
            "selected_cv_lane": st.column_config.TextColumn("Selected CV lane"),
            "cv_selection_status": st.column_config.TextColumn("CV selection", width="small"),
            "cv_status": st.column_config.TextColumn("CV status", width="small"),
            "open_cv": st.column_config.TextColumn("Open CV", width="small"),
            "application_status": st.column_config.TextColumn("Application status"),
            "next_action": st.column_config.TextColumn("Next action"),
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
    selected_ids = selected_job_ids(
        rows,
        table_state.selection.rows,  # type: ignore[attr-defined]
    )
    st.session_state[SELECTED_JOB_IDS_KEY] = selected_ids
    selected_count = len(selected_ids)
    label = "job" if selected_count == 1 else "jobs"
    st.caption(f"{selected_count} {label} selected.")
    selected_job_id = selected_ids[0] if selected_count == 1 else None
    if st.button(
        "Open selected job",
        key="open_selected_job",
        type="primary",
        disabled=selected_job_id is None,
    ):
        st.switch_page(
            "pages/job_details.py",
            query_params={"job_id": str(selected_job_id)},
        )

    try:
        assessment_eligibility = assessment_batch_service.selection_eligibility(selected_ids)
    except JobNotFoundError:
        logger.exception(
            "jobs_dashboard_assessment_eligibility_missing_job job_ids=%s", selected_ids
        )
        st.error("One or more selected jobs no longer exist. Refresh the selection and try again.")
        return
    except SQLAlchemyError:
        logger.exception(
            "jobs_dashboard_assessment_eligibility_load_failed job_ids=%s", selected_ids
        )
        st.error(LOAD_ERROR_MESSAGE)
        return

    if assessment_eligibility.initial_assessment_job_ids:
        _render_assess_selected_jobs(assessment_batch_service, selected_ids)
    if assessment_eligibility.reassessment_job_ids:
        _render_reassess_selected_jobs(assessment_batch_service, selected_ids)
    _render_select_for_cv_generation(cv_selection_service, selected_ids)
    _render_delete_selected_jobs(service, selected_ids)


def _render_assess_selected_jobs(
    service: AssessmentBatchService,
    selected_ids: tuple[int, ...],
) -> None:
    """Require explicit confirmation before queuing selected initial assessments."""

    if not selected_ids:
        return
    if st.session_state.get(ASSESSMENT_CONFIRMATION_IDS_KEY) != selected_ids:
        st.session_state[ASSESSMENT_CONFIRMATION_IDS_KEY] = selected_ids
        st.session_state[ASSESSMENT_CONFIRMATION_KEY] = False

    count = len(selected_ids)
    noun = "job" if count == 1 else "jobs"
    st.divider()
    st.info(f"Queue initial assessments for {count} selected {noun}.")
    confirmed = st.checkbox(
        f"I want to assess these {count} selected {noun}.",
        key=ASSESSMENT_CONFIRMATION_KEY,
    )
    if not st.button(
        f"Assess selected {noun}",
        key="assess_selected_jobs",
        type="primary",
        disabled=not confirmed,
    ):
        return

    try:
        result = service.queue_selected(selected_ids)
    except JobNotFoundError:
        logger.exception("jobs_dashboard_assessment_missing_job job_ids=%s", selected_ids)
        st.error("One or more selected jobs no longer exist. Refresh the selection and try again.")
        return
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_assessment_queue_failed job_ids=%s", selected_ids)
        st.error(
            "The selected assessments could not be queued. See the private UI log for details."
        )
        return

    if result.batch_id is None:
        st.warning("None of the selected jobs are eligible for an initial assessment.")
        return

    queued_count = len(result.queued_job_ids)
    queued_noun = "job" if queued_count == 1 else "jobs"
    message = f"Queued {queued_count} {queued_noun} for assessment in batch {result.batch_id}."
    if result.skipped:
        message += f" Skipped {len(result.skipped)} ineligible selected jobs."
    st.session_state[ASSESSMENT_SUCCESS_KEY] = message
    clear_dashboard_selection()
    st.rerun()


def _render_reassess_selected_jobs(
    service: AssessmentBatchService,
    selected_ids: tuple[int, ...],
) -> None:
    """Require explicit confirmation before queuing stale or failed reassessments."""

    if not selected_ids:
        return
    if st.session_state.get(REASSESSMENT_CONFIRMATION_IDS_KEY) != selected_ids:
        st.session_state[REASSESSMENT_CONFIRMATION_IDS_KEY] = selected_ids
        st.session_state[REASSESSMENT_CONFIRMATION_KEY] = False

    count = len(selected_ids)
    noun = "job" if count == 1 else "jobs"
    st.divider()
    st.info(f"Queue reassessments for {count} selected {noun} with failed or stale assessments.")
    confirmed = st.checkbox(
        f"I want to reassess these {count} selected {noun}.",
        key=REASSESSMENT_CONFIRMATION_KEY,
    )
    if not st.button(
        f"Reassess selected {noun}",
        key="reassess_selected_jobs",
        disabled=not confirmed,
    ):
        return

    try:
        result = service.queue_reassessment_selected(selected_ids)
    except JobNotFoundError:
        logger.exception("jobs_dashboard_reassessment_missing_job job_ids=%s", selected_ids)
        st.error("One or more selected jobs no longer exist. Refresh the selection and try again.")
        return
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_reassessment_queue_failed job_ids=%s", selected_ids)
        st.error(
            "The selected reassessments could not be queued. See the private UI log for details."
        )
        return

    if result.batch_id is None:
        st.warning("None of the selected jobs are eligible for reassessment.")
        return

    queued_count = len(result.queued_job_ids)
    queued_noun = "job" if queued_count == 1 else "jobs"
    message = f"Queued {queued_count} {queued_noun} for reassessment in batch {result.batch_id}."
    if result.skipped:
        message += f" Skipped {len(result.skipped)} ineligible selected jobs."
    st.session_state[REASSESSMENT_SUCCESS_KEY] = message
    clear_dashboard_selection()
    st.rerun()


def _render_select_for_cv_generation(
    service: CvSelectionService,
    selected_ids: tuple[int, ...],
) -> None:
    """Require explicit confirmation before marking jobs ready for later generation."""

    if not selected_ids:
        return
    if st.session_state.get(CV_SELECTION_CONFIRMATION_IDS_KEY) != selected_ids:
        st.session_state[CV_SELECTION_CONFIRMATION_IDS_KEY] = selected_ids
        st.session_state[CV_SELECTION_CONFIRMATION_KEY] = False

    count = len(selected_ids)
    noun = "job" if count == 1 else "jobs"
    st.divider()
    st.info(
        f"Mark {count} selected {noun} as ready for CV generation. This does not start generation."
    )
    confirmed = st.checkbox(
        f"I want to select these {count} {noun} for CV generation.",
        key=CV_SELECTION_CONFIRMATION_KEY,
    )
    if not st.button(
        f"Select {noun} for CV generation",
        key="select_for_cv_generation",
        disabled=not confirmed,
    ):
        return

    try:
        result = service.select_jobs(selected_ids)
    except JobNotFoundError:
        logger.exception("jobs_dashboard_cv_selection_missing_job job_ids=%s", selected_ids)
        st.error("One or more selected jobs no longer exist. Refresh the selection and try again.")
        return
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_cv_selection_failed job_ids=%s", selected_ids)
        st.error("The selected jobs could not be marked for CV generation. See the private UI log.")
        return

    if not result.selected_job_ids:
        st.warning(_cv_selection_skip_summary(result))
        return

    selected_count = len(result.selected_job_ids)
    selected_noun = "job" if selected_count == 1 else "jobs"
    message = f"Selected {selected_count} {selected_noun} for later CV generation."
    if result.skipped:
        message += f" {_cv_selection_skip_summary(result)}"
    st.session_state[CV_SELECTION_SUCCESS_KEY] = message
    clear_dashboard_selection()
    st.rerun()


def _cv_selection_skip_summary(result: CvSelectionResult) -> str:
    """Translate durable skip reasons into an actionable concise UI message."""

    labels = {
        CvSelectionSkipReason.NOT_PURSUED: "not marked Pursue",
        CvSelectionSkipReason.MISSING_ASSESSMENT: "missing an assessment",
        CvSelectionSkipReason.ASSESSMENT_NOT_READY: "assessment is not successfully completed",
        CvSelectionSkipReason.ASSESSMENT_STALE: "assessment is stale",
        CvSelectionSkipReason.MISSING_CV_LANE: "missing a confirmed CV lane",
        CvSelectionSkipReason.ALREADY_SELECTED: "already selected",
    }
    details = "; ".join(f"job {skip.job_id}: {labels[skip.reason]}" for skip in result.skipped)
    return f"Skipped {len(result.skipped)} ineligible selected jobs ({details})."


def _render_delete_selected_jobs(service: JobService, selected_ids: tuple[int, ...]) -> None:
    """Require an explicit, selection-bound confirmation before permanent deletion."""

    if not selected_ids:
        return
    if st.session_state.get(DELETE_CONFIRMATION_IDS_KEY) != selected_ids:
        st.session_state[DELETE_CONFIRMATION_IDS_KEY] = selected_ids
        st.session_state[DELETE_CONFIRMATION_KEY] = False

    count = len(selected_ids)
    noun = "job" if count == 1 else "jobs"
    st.divider()
    st.warning(
        f"Permanently delete {count} selected {noun}, including local assessment, "
        "background-task, and model-call history. This cannot be undone."
    )
    confirmed = st.checkbox(
        f"I understand that these {count} {noun} and their linked local history will be deleted.",
        key=DELETE_CONFIRMATION_KEY,
    )
    if not st.button(
        f"Delete selected {noun}",
        key="delete_selected_jobs",
        type="secondary",
        disabled=not confirmed,
    ):
        return
    try:
        deleted = service.delete_many(selected_ids)
    except JobNotFoundError:
        logger.exception("jobs_dashboard_delete_missing_job job_ids=%s", selected_ids)
        st.error("One or more selected jobs no longer exist. Refresh the selection and try again.")
        return
    except SQLAlchemyError:
        logger.exception("jobs_dashboard_delete_failed job_ids=%s", selected_ids)
        st.error("The selected jobs could not be deleted. See the private UI log for details.")
        return

    st.session_state[DELETE_SUCCESS_KEY] = f"Deleted {deleted} {noun} and linked local history."
    clear_dashboard_selection()
    st.rerun()


def clear_dashboard_selection() -> None:
    """Clear stable IDs and Streamlit's row-position selection."""

    # Streamlit forbids changing a widget's state after it has been created in
    # the current script run. Defer the table reset until the following rerun,
    # before ``st.dataframe`` is instantiated again.
    st.session_state[CLEAR_TABLE_SELECTION_ON_RERUN_KEY] = True
    st.session_state[SELECTED_JOB_IDS_KEY] = ()
    st.session_state[DELETE_CONFIRMATION_IDS_KEY] = ()
    st.session_state[ASSESSMENT_CONFIRMATION_IDS_KEY] = ()
    st.session_state[REASSESSMENT_CONFIRMATION_IDS_KEY] = ()
    st.session_state[CV_SELECTION_CONFIRMATION_IDS_KEY] = ()


def _clear_table_selection_if_requested() -> None:
    """Reset the dataframe selection before its widget is created on a rerun."""

    if st.session_state.pop(CLEAR_TABLE_SELECTION_ON_RERUN_KEY, False):
        st.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": []}}
