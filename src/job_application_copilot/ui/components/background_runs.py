"""Background task monitoring, filtering, attempt history, and retry controls."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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
INCLUDE_COMPLETED_KEY = "background_runs_include_completed"
STATUS_QUERY_PARAMETER = "status"
LOAD_ERROR_MESSAGE = "Background runs could not be loaded. See the private UI log for details."
RETRY_ERROR_MESSAGE = "The task could not be retried. See the private UI log for details."
AUTO_REFRESH_SECONDS = 60
BACKGROUND_RUNS_TABLE_KEY = "background_runs_table"
TABLE_COLUMN_ORDER = (
    "batch",
    "job",
    "operation",
    "status",
    "pipeline_step",
    "started",
    "completed",
    "duration",
    "error",
)


@dataclass(frozen=True, slots=True)
class BackgroundRunTableRow:
    """Compact presentation values for one durable background task."""

    run: BackgroundRunSummary

    def display_record(self) -> dict[str, object]:
        """Return the stable values rendered in the compact runs table."""

        return {
            "batch": f"Batch {self.run.batch_id}",
            "job": f"{self.run.company} — {self.run.job_title}",
            "operation": self.run.operation.value,
            "status": self.run.status.value,
            "pipeline_step": self.run.pipeline_step or "—",
            "started": _format_timestamp(self.run.started_at),
            "completed": _format_timestamp(self.run.completed_at),
            "duration": _format_duration(self.run.started_at, self.run.completed_at),
            "error": _error_indicator(self.run),
        }


def shape_background_run_rows(
    runs: Iterable[BackgroundRunSummary],
) -> tuple[BackgroundRunTableRow, ...]:
    """Create compact rows without changing durable monitoring state."""

    return tuple(BackgroundRunTableRow(run) for run in runs)


def selected_background_run(
    rows: Sequence[BackgroundRunTableRow],
    selected_positions: Iterable[int],
) -> BackgroundRunSummary | None:
    """Return the selected task while protecting the table's stable identity."""

    positions = tuple(selected_positions)
    if not positions:
        return None
    if len(positions) != 1:
        raise ValueError("Select exactly one background task.")
    position = positions[0]
    if position < 0 or position >= len(rows):
        raise ValueError(f"Selected row position {position} is outside the background runs table.")
    return rows[position].run


def render_background_runs(service: BackgroundRunService) -> None:
    """Render filters and current durable background-task state."""

    _apply_status_query_parameter()
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
    include_completed = st.checkbox(
        "Include completed tasks",
        key=INCLUDE_COMPLETED_KEY,
    )
    return BackgroundRunFilters(
        operation=operation,
        status=status,
        batch_id=batch_id,
        job_id=job_id,
        include_completed=include_completed,
    )


def _apply_status_query_parameter() -> None:
    """Apply one valid linked status filter before its widget is created."""

    value = st.query_params.get(STATUS_QUERY_PARAMETER)
    if value is None:
        return
    try:
        st.session_state[FILTER_STATUS_KEY] = BackgroundTaskStatus(value)
    except ValueError:
        pass
    finally:
        st.query_params.clear()


def _render_run_rows(
    service: BackgroundRunService,
    runs: list[BackgroundRunSummary],
) -> None:
    st.caption(f"{len(runs)} background task{'s' if len(runs) != 1 else ''}.")
    rows = shape_background_run_rows(runs)
    table_state = st.dataframe(
        [row.display_record() for row in rows],
        key=BACKGROUND_RUNS_TABLE_KEY,
        hide_index=True,
        column_order=TABLE_COLUMN_ORDER,
        column_config={
            "batch": st.column_config.TextColumn("Batch", width="small"),
            "job": st.column_config.TextColumn("Job"),
            "operation": st.column_config.TextColumn("Operation", width="small"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "pipeline_step": st.column_config.TextColumn("Pipeline step"),
            "started": st.column_config.TextColumn("Started"),
            "completed": st.column_config.TextColumn("Completed"),
            "duration": st.column_config.TextColumn("Duration", width="small"),
            "error": st.column_config.TextColumn("Error", width="small"),
        },
        on_select="rerun",
        selection_mode="single-row",
        width="stretch",
    )
    selected_run = selected_background_run(
        rows,
        table_state.selection.rows,  # type: ignore[attr-defined]
    )
    if selected_run is not None:
        _render_selected_run_details(service, selected_run)


def _render_selected_run_details(service: BackgroundRunService, run: BackgroundRunSummary) -> None:
    """Render full diagnostics and retry only for the selected compact row."""

    with st.expander(f"Task {run.task_id} details", expanded=True):
        st.caption(
            f"Batch {run.batch_id} · {_format_timestamp(run.batch_created_at)} · Job {run.job_id}"
        )
        if run.error_message:
            st.error(run.error_message)
        elif run.status is BackgroundTaskStatus.PENDING and run.retry_count:
            st.caption("Queued for retry.")
        else:
            st.caption("No error.")

        if run.retryable and st.button(
            "Retry",
            key=f"background_run_retry_{run.task_id}",
            type="primary",
        ):
            _retry_task(service, run.task_id)

        if run.attempts:
            st.markdown(f"**Attempt history ({len(run.attempts)})**")
            st.dataframe(
                [
                    {
                        "attempt": attempt.attempt_number,
                        "status": attempt.status.value,
                        "pipeline_step": attempt.pipeline_step or "—",
                        "started": _format_timestamp(attempt.started_at),
                        "completed": _format_timestamp(attempt.completed_at),
                        "duration": _format_duration(attempt.started_at, attempt.completed_at),
                        "error": attempt.error_message or "—",
                    }
                    for attempt in run.attempts
                ],
                hide_index=True,
                width="stretch",
            )


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
            filters.include_completed,
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


def _error_indicator(run: BackgroundRunSummary) -> str:
    """Return a compact status signal while retaining details on selection."""

    if run.error_message:
        return "Error"
    if run.status is BackgroundTaskStatus.PENDING and run.retry_count:
        return "Queued for retry"
    return "—"
