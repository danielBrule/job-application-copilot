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
    _format_duration,
    _format_timestamp,
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

    runs = BackgroundRunService(migrated_database).list()

    assert [run.task_id for run in runs] == [newer_id, older_id]
    assert runs[0].company == "Newer"
    assert runs[0].retryable
    assert runs[0].attempts[0].attempt_number == 1
    assert runs[0].attempts[0].status is BackgroundTaskStatus.FAILED
    assert runs[0].attempts[0].error_message == "Handler failed."


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
    runs = {run.task_id: run for run in service.list()}

    assert result.status is BackgroundTaskStatus.PENDING
    assert runs[failed_id].status is BackgroundTaskStatus.PENDING
    assert runs[failed_id].retry_count == 1
    assert runs[failed_id].attempts[0].status is BackgroundTaskStatus.FAILED
    assert runs[completed_id].status is BackgroundTaskStatus.COMPLETED


def test_formats_utc_timestamps_and_durations() -> None:
    started = datetime(2026, 7, 29, 9, 0, 0)
    completed = datetime(2026, 7, 29, 10, 2, 3)

    assert _format_timestamp(started) == "2026-07-29 09:00:00 UTC"
    assert _format_timestamp(None) == "—"
    assert _format_duration(started, completed) == "1h 02m 03s"
    assert _format_duration(None, completed) == "—"
