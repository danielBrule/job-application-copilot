"""Tests for background-run monitoring queries and retry history."""

from datetime import date, datetime
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundRunFilters,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    create_database,
)
from job_application_copilot.repositories.models import (
    BackgroundBatch,
    BackgroundTask,
    Job,
)
from job_application_copilot.services.background_runs import BackgroundRunService
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.ui.components.background_runs import (
    TABLE_COLUMN_ORDER,
    _format_duration,
    _format_timestamp,
    selected_background_run,
    shape_background_run_rows,
)


@pytest.fixture
def migrated_database(tmp_path: Path) -> Database:
    database_path = tmp_path / "copilot.db"
    initialize_database(database_path)
    database = create_database(database_path)
    try:
        yield database
    finally:
        database.dispose()


def add_task(
    database: Database,
    *,
    company: str,
    operation: BackgroundOperation,
    status: BackgroundTaskStatus,
    batch_created_at: datetime,
) -> int:
    with database.session() as session:
        job = Job(
            company=company,
            job_title="Platform Engineer",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Build reliable systems.",
            date_added=date(2026, 7, 29),
        )
        session.add(job)
        session.flush()
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=operation, created_at=batch_created_at)
        )
        task = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job.id,
                operation=operation,
            )
        )
        if status is not BackgroundTaskStatus.PENDING:
            BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)
        if (
            status is not BackgroundTaskStatus.RUNNING
            and status is not BackgroundTaskStatus.PENDING
        ):
            BackgroundTaskRepository(session).transition(
                task,
                status,
                error_message="Handler failed." if status is BackgroundTaskStatus.FAILED else None,
            )
        return task.id


def test_lists_newest_batches_with_job_and_attempt_history(
    migrated_database: Database,
) -> None:
    older_id = add_task(
        migrated_database,
        company="Older",
        operation=BackgroundOperation.CV_GENERATION,
        status=BackgroundTaskStatus.COMPLETED,
        batch_created_at=datetime(2026, 7, 29, 8, 0),
    )
    newer_id = add_task(
        migrated_database,
        company="Newer",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )

    runs = BackgroundRunService(migrated_database).list(
        BackgroundRunFilters(include_completed=True)
    )

    assert [run.task_id for run in runs] == [newer_id, older_id]
    assert runs[0].company == "Newer"
    assert runs[0].retryable
    assert runs[0].attempts[0].attempt_number == 1
    assert runs[0].attempts[0].status is BackgroundTaskStatus.FAILED
    assert runs[0].attempts[0].error_message == "Handler failed."


def test_failed_task_count_includes_only_failed_supported_operations(
    migrated_database: Database,
) -> None:
    add_task(
        migrated_database,
        company="Failed assessment",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 8, 0),
    )
    add_task(
        migrated_database,
        company="Failed CV",
        operation=BackgroundOperation.CV_GENERATION,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    add_task(
        migrated_database,
        company="Interrupted",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.INTERRUPTED,
        batch_created_at=datetime(2026, 7, 29, 10, 0),
    )
    add_task(
        migrated_database,
        company="Completed",
        operation=BackgroundOperation.CV_GENERATION,
        status=BackgroundTaskStatus.COMPLETED,
        batch_created_at=datetime(2026, 7, 29, 11, 0),
    )

    assert BackgroundRunService(migrated_database).failed_task_count() == 2


def test_hides_completed_tasks_by_default_and_includes_them_on_request(
    migrated_database: Database,
) -> None:
    completed_id = add_task(
        migrated_database,
        company="Completed",
        operation=BackgroundOperation.CV_GENERATION,
        status=BackgroundTaskStatus.COMPLETED,
        batch_created_at=datetime(2026, 7, 29, 8, 0),
    )
    failed_id = add_task(
        migrated_database,
        company="Failed",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    interrupted_id = add_task(
        migrated_database,
        company="Interrupted",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.INTERRUPTED,
        batch_created_at=datetime(2026, 7, 29, 10, 0),
    )
    running_id = add_task(
        migrated_database,
        company="Running",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.RUNNING,
        batch_created_at=datetime(2026, 7, 29, 11, 0),
    )
    pending_id = add_task(
        migrated_database,
        company="Pending",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.PENDING,
        batch_created_at=datetime(2026, 7, 29, 12, 0),
    )

    service = BackgroundRunService(migrated_database)

    assert [run.task_id for run in service.list()] == [
        pending_id,
        running_id,
        interrupted_id,
        failed_id,
    ]
    assert [run.task_id for run in service.list(BackgroundRunFilters(include_completed=True))] == [
        pending_id,
        running_id,
        interrupted_id,
        failed_id,
        completed_id,
    ]


def test_applies_all_exact_monitoring_filters(migrated_database: Database) -> None:
    matching_id = add_task(
        migrated_database,
        company="Match",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    add_task(
        migrated_database,
        company="Other",
        operation=BackgroundOperation.CV_GENERATION,
        status=BackgroundTaskStatus.COMPLETED,
        batch_created_at=datetime(2026, 7, 29, 8, 0),
    )
    matching = BackgroundRunService(migrated_database).list()[0]

    runs = BackgroundRunService(migrated_database).list(
        BackgroundRunFilters(
            operation=BackgroundOperation.ASSESSMENT,
            status=BackgroundTaskStatus.FAILED,
            batch_id=matching.batch_id,
            job_id=matching.job_id,
            include_completed=True,
        )
    )

    assert [run.task_id for run in runs] == [matching_id]


def test_retry_preserves_failed_attempt_and_does_not_change_completed_sibling(
    migrated_database: Database,
) -> None:
    failed_id = add_task(
        migrated_database,
        company="Failed",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    service = BackgroundRunService(migrated_database)
    failed_run = service.list()[0]
    with migrated_database.session() as session:
        completed_job = Job(
            company="Completed",
            job_title="Platform Engineer",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_description="Build reliable systems.",
            date_added=date(2026, 7, 29),
        )
        session.add(completed_job)
        session.flush()
        completed = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=failed_run.batch_id,
                job_id=completed_job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )
        BackgroundTaskRepository(session).transition(completed, BackgroundTaskStatus.RUNNING)
        BackgroundTaskRepository(session).transition(completed, BackgroundTaskStatus.COMPLETED)
        completed_id = completed.id

    result = service.retry_task(failed_id)
    runs = {run.task_id: run for run in service.list(BackgroundRunFilters(include_completed=True))}

    assert result.status is BackgroundTaskStatus.PENDING
    assert runs[failed_id].status is BackgroundTaskStatus.PENDING
    assert runs[failed_id].retry_count == 1
    assert runs[failed_id].attempts[0].status is BackgroundTaskStatus.FAILED
    assert runs[completed_id].status is BackgroundTaskStatus.COMPLETED


def test_retry_all_failed_tasks_preserves_attempts_and_skips_other_states(
    migrated_database: Database,
) -> None:
    failed_assessment_id = add_task(
        migrated_database,
        company="Failed assessment",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 8, 0),
    )
    failed_cv_id = add_task(
        migrated_database,
        company="Failed CV",
        operation=BackgroundOperation.CV_GENERATION,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    interrupted_id = add_task(
        migrated_database,
        company="Interrupted",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.INTERRUPTED,
        batch_created_at=datetime(2026, 7, 29, 10, 0),
    )

    results = BackgroundRunService(migrated_database).retry_all_failed_tasks()
    runs = {
        run.task_id: run
        for run in BackgroundRunService(migrated_database).list(
            BackgroundRunFilters(include_completed=True)
        )
    }

    assert [result.task_id for result in results] == [failed_assessment_id, failed_cv_id]
    assert all(result.status is BackgroundTaskStatus.PENDING for result in results)
    assert all(result.retry_count == 1 for result in results)
    assert runs[failed_assessment_id].status is BackgroundTaskStatus.PENDING
    assert runs[failed_assessment_id].attempts[0].status is BackgroundTaskStatus.FAILED
    assert runs[failed_cv_id].status is BackgroundTaskStatus.PENDING
    assert runs[failed_cv_id].attempts[0].status is BackgroundTaskStatus.FAILED
    assert runs[interrupted_id].status is BackgroundTaskStatus.INTERRUPTED


def test_retry_all_failed_tasks_returns_no_results_when_none_are_failed(
    migrated_database: Database,
) -> None:
    add_task(
        migrated_database,
        company="Pending",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.PENDING,
        batch_created_at=datetime(2026, 7, 29, 8, 0),
    )

    assert BackgroundRunService(migrated_database).retry_all_failed_tasks() == ()


def test_shapes_compact_rows_and_preserves_selected_task(migrated_database: Database) -> None:
    task_id = add_task(
        migrated_database,
        company="Failed",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.FAILED,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    (row,) = shape_background_run_rows(BackgroundRunService(migrated_database).list())

    assert tuple(row.display_record()) == TABLE_COLUMN_ORDER
    assert row.display_record()["job"] == "Failed — Platform Engineer"
    assert row.display_record()["status"] == "FAILED"
    assert row.display_record()["error"] == "Error"
    assert selected_background_run((row,), [0]).task_id == task_id
    assert selected_background_run((row,), []) is None


@pytest.mark.parametrize("selected_positions", [(-1,), (1,), (0, 1)])
def test_invalid_compact_table_selection_is_rejected(
    migrated_database: Database,
    selected_positions: tuple[int, ...],
) -> None:
    add_task(
        migrated_database,
        company="Pending",
        operation=BackgroundOperation.ASSESSMENT,
        status=BackgroundTaskStatus.PENDING,
        batch_created_at=datetime(2026, 7, 29, 9, 0),
    )
    rows = shape_background_run_rows(BackgroundRunService(migrated_database).list())

    with pytest.raises(ValueError):
        selected_background_run(rows, selected_positions)


def test_formats_utc_timestamps_and_durations() -> None:
    started = datetime(2026, 7, 29, 9, 0, 0)
    completed = datetime(2026, 7, 29, 10, 2, 3)

    assert _format_timestamp(started) == "2026-07-29 09:00:00 UTC"
    assert _format_timestamp(None) == "—"
    assert _format_duration(started, completed) == "1h 02m 03s"
    assert _format_duration(None, completed) == "—"
