"""Background task monitoring, filtering, attempt history, and retry controls."""

from datetime import datetime

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundRunFilters,
    BackgroundRunSummary,
    BackgroundTaskStatus,
)
from job_application_copilot.errors import ApplicationError
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.models.common import utc_now
from job_application_copilot.services.background_runs import BackgroundRunService

logger = get_logger(__name__)

REFRESH_BUTTON_KEY = "background_runs_refresh"
FILTER_OPERATION_KEY = "background_runs_operation"
FILTER_STATUS_KEY = "background_runs_status"
FILTER_BATCH_KEY = "background_runs_batch"
FILTER_JOB_KEY = "background_runs_job"
LOAD_ERROR_MESSAGE = "Background runs could not be loaded. See the private UI log for details."
RETRY_ERROR_MESSAGE = "The task could not be retried. See the private UI log for details."
AUTO_REFRESH_SECONDS = 60


def render_background_runs(service: BackgroundRunService) -> None:
    """Render filters and current durable background-task state."""

    st.title("Background Runs")
    heading_columns = st.columns([1, 5])
    with heading_columns[0]:
        if st.button("Refresh now", key=REFRESH_BUTTON_KEY):
            st.rerun()
    with heading_columns[1]:
        st.caption(
            "Active results refresh every 60 seconds. Refreshing this page does not control "
            "the worker."
        )

    try:
        all_runs = service.list()
    except SQLAlchemyError:
        logger.exception("background_runs_load_failed")
        st.error(LOAD_ERROR_MESSAGE)
        return

    if not all_runs:
        st.info("No background tasks have been created yet.")
        return

    filters = _render_filters(all_runs)
    try:
        runs = service.list(filters) if _has_active_filters(filters) else all_runs
    except SQLAlchemyError:
        logger.exception("background_runs_filter_failed")
        st.error(LOAD_ERROR_MESSAGE)
        return

    if not runs:
        st.info("No background tasks match the current filters.")
        return

    if any(run.active for run in runs):
        _render_polling_runs(service, filters)
    else:
        _render_run_rows(service, runs)


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _render_polling_runs(
    service: BackgroundRunService,
    filters: BackgroundRunFilters,
) -> None:
    """Refresh only the active result section once per minute."""

    try:
        runs = service.list(filters)
    except SQLAlchemyError:
        logger.exception("background_runs_refresh_failed")
        st.error(LOAD_ERROR_MESSAGE)
        return
    if not any(run.active for run in runs):
        st.rerun()
    _render_run_rows(service, runs)


def _render_filters(runs: list[BackgroundRunSummary]) -> BackgroundRunFilters:
    batches = {
        run.batch_id: f"Batch {run.batch_id} — {_format_timestamp(run.batch_created_at)}"
        for run in runs
    }
    jobs = {run.job_id: f"{run.company} — {run.job_title} (Job {run.job_id})" for run in runs}
    columns = st.columns(4)
    with columns[0]:
        operation = st.selectbox(
            "Operation",
            options=[None, *BackgroundOperation],
            format_func=lambda value: "All operations" if value is None else value.value,
            key=FILTER_OPERATION_KEY,
        )
    with columns[1]:
        status = st.selectbox(
            "Status",
            options=[None, *BackgroundTaskStatus],
            format_func=lambda value: "All statuses" if value is None else value.value,
            key=FILTER_STATUS_KEY,
        )
    with columns[2]:
        batch_id = st.selectbox(
            "Batch",
            options=[None, *batches],
            format_func=lambda value: "All batches" if value is None else batches[value],
            key=FILTER_BATCH_KEY,
        )
    with columns[3]:
        job_id = st.selectbox(
            "Job",
            options=[None, *jobs],
            format_func=lambda value: "All jobs" if value is None else jobs[value],
            key=FILTER_JOB_KEY,
        )
    return BackgroundRunFilters(
        operation=operation,
        status=status,
        batch_id=batch_id,
        job_id=job_id,
    )


def _render_run_rows(
    service: BackgroundRunService,
    runs: list[BackgroundRunSummary],
) -> None:
    st.caption(f"{len(runs)} background task{'s' if len(runs) != 1 else ''}.")
    for run in runs:
        with st.container(border=True):
            identity, timing, result, action = st.columns([3, 2, 3, 1])
            with identity:
                st.markdown(f"**{run.company} — {run.job_title}**")
                st.caption(
                    f"Batch {run.batch_id} · {_format_timestamp(run.batch_created_at)} · "
                    f"{run.operation.value}"
                )
            with timing:
                st.markdown(f"**{run.status.value}**")
                st.caption(
                    f"Started: {_format_timestamp(run.started_at)}  \n"
                    f"Completed: {_format_timestamp(run.completed_at)}  \n"
                    f"Duration: {_format_duration(run.started_at, run.completed_at)}"
                )
            with result:
                if run.pipeline_step:
                    st.caption(f"Pipeline step: {run.pipeline_step}")
                if run.error_message:
                    st.error(run.error_message)
                elif run.status is BackgroundTaskStatus.PENDING and run.retry_count:
                    st.caption("Queued for retry.")
                else:
                    st.caption("No error.")
            with action:
                if run.retryable and st.button(
                    "Retry",
                    key=f"background_run_retry_{run.task_id}",
                    type="primary",
                ):
                    _retry_task(service, run.task_id)

            if run.attempts:
                with st.expander(
                    f"Attempt history ({len(run.attempts)})",
                    expanded=run.retryable,
                ):
                    for attempt in run.attempts:
                        st.markdown(
                            f"**Attempt {attempt.attempt_number} — {attempt.status.value}**  \n"
                            f"Started: {_format_timestamp(attempt.started_at)} · "
                            f"Completed: {_format_timestamp(attempt.completed_at)} · "
                            f"Duration: "
                            f"{_format_duration(attempt.started_at, attempt.completed_at)}"
                        )
                        if attempt.pipeline_step:
                            st.caption(f"Pipeline step: {attempt.pipeline_step}")
                        if attempt.error_message:
                            st.error(attempt.error_message)


def _retry_task(service: BackgroundRunService, task_id: int) -> None:
    try:
        result = service.retry_task(task_id)
    except ApplicationError as error:
        st.error(str(error))
        return
    except SQLAlchemyError:
        logger.exception("background_task_retry_failed task_id=%s", task_id)
        st.error(RETRY_ERROR_MESSAGE)
        return

    st.success(f"Task {result.task_id} queued for retry (retry {result.retry_count}).")
    st.rerun()


def _has_active_filters(filters: BackgroundRunFilters) -> bool:
    return any(
        value is not None
        for value in (
            filters.operation,
            filters.status,
            filters.batch_id,
            filters.job_id,
        )
    )


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return f"{value:%Y-%m-%d %H:%M:%S} UTC"


def _format_duration(started_at: datetime | None, completed_at: datetime | None) -> str:
    if started_at is None:
        return "—"
    end = completed_at or utc_now()
    total_seconds = max(0, int((end - started_at).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"
