"""Operational KPI dashboard presentation."""

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.observability import get_logger
from job_application_copilot.services import (
    BackgroundRunService,
    DashboardKpiService,
    DashboardUsageKpis,
    DashboardWorkflowKpis,
)

logger = get_logger(__name__)
LOAD_ERROR_MESSAGE = "The dashboard could not be loaded. See the private UI log for details."


def render_dashboard(
    dashboard_kpi_service: DashboardKpiService,
    background_run_service: BackgroundRunService,
) -> None:
    """Render global usage, processing, and failed-task KPIs."""

    st.title("Dashboard")
    try:
        _render_usage_kpis(dashboard_kpi_service.usage())
        _render_workflow_kpis(dashboard_kpi_service.workflow())
        _render_failed_task_kpi(background_run_service.failed_task_count())
    except SQLAlchemyError:
        logger.exception("dashboard_kpi_load_failed")
        st.error(LOAD_ERROR_MESSAGE)


def _render_usage_kpis(kpis: DashboardUsageKpis) -> None:
    """Render global token and processing-time KPI cards."""

    st.subheader("Usage and processing")
    st.caption("Average per successful LLM call / total")
    assessment_tokens, cv_tokens = st.columns(2)
    with assessment_tokens:
        st.metric(
            "Assessment tokens",
            _total_and_average(
                kpis.assessment.total_tokens, kpis.assessment.average_tokens_per_successful_call
            ),
        )
    with cv_tokens:
        st.metric(
            "CV-generation tokens",
            _total_and_average(
                kpis.cv_generation.total_tokens,
                kpis.cv_generation.average_tokens_per_successful_call,
            ),
        )
    assessment_duration, cv_duration = st.columns(2)
    with assessment_duration:
        st.metric(
            "Assessment processing time",
            _duration_total_and_average(
                kpis.assessment.total_duration_seconds,
                kpis.assessment.average_duration_seconds_per_successful_call,
            ),
        )
    with cv_duration:
        st.metric(
            "CV-generation processing time",
            _duration_total_and_average(
                kpis.cv_generation.total_duration_seconds,
                kpis.cv_generation.average_duration_seconds_per_successful_call,
            ),
        )


def _render_workflow_kpis(kpis: DashboardWorkflowKpis) -> None:
    """Render a compact view of the job-to-submission workflow."""

    st.subheader("Workflow")
    jobs, assessed, applied, interviews, rejected = st.columns(5)
    jobs.metric("Jobs", kpis.jobs_entered)
    assessed.metric("Assessed jobs", kpis.assessed_jobs)
    applied.metric("Applied jobs", kpis.applied_jobs)
    interviews.metric("Interviews ongoing", kpis.interviews_ongoing)
    rejected.metric("Rejected jobs", kpis.rejected_jobs)
    st.subheader("Current queues")
    unassessed, cv_generation = st.columns(2)
    unassessed.metric("Unassessed jobs", kpis.unassessed_jobs)
    cv_generation.metric(
        "Selected without generated CV",
        kpis.selected_jobs_without_generated_cv,
    )


def _render_failed_task_kpi(failed_task_count: int) -> None:
    """Render failed-task attention KPI and filtered Background Runs navigation."""

    st.subheader("Attention needed")
    failed_tasks, _ = st.columns((1, 3))
    with failed_tasks:
        st.metric("Failed tasks requiring attention", failed_task_count)
        st.page_link(
            "pages/background_runs.py",
            label="Review failed tasks",
            query_params={"status": "FAILED"},
        )


def _total_and_average(total: int, average: float | None) -> str:
    """Format a token total and optional successful-call average."""

    average_display = "—" if average is None else f"{average:,.1f}"
    return f"{average_display} avg / {total:,} total"


def _duration_total_and_average(total: float, average: float | None) -> str:
    """Format duration values in seconds with an optional successful-call average."""

    average_display = "—" if average is None else f"{average:.2f} s"
    return f"{average_display} avg / {total:.2f} s total"
