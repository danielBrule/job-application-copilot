"""Integration tests for background-task recovery and explicit retry."""

from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
    Database,
    InvalidBackgroundTaskTransitionError,
    create_database,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask, Job
from job_application_copilot.services.background_task_recovery import (
    INTERRUPTED_BY_WORKER_RESTART_MESSAGE,
    BackgroundTaskRecoveryService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


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
    company: str,
    *,
    status: BackgroundTaskStatus,
) -> BackgroundTask:
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
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        task = BackgroundTaskRepository(session).add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )
        if status is not BackgroundTaskStatus.PENDING:
            BackgroundTaskRepository(session).transition(task, BackgroundTaskStatus.RUNNING)
        if status in {BackgroundTaskStatus.COMPLETED, BackgroundTaskStatus.FAILED}:
            BackgroundTaskRepository(session).transition(
                task,
                status,
                error_message="Handler failed." if status is BackgroundTaskStatus.FAILED else None,
            )
        return task


def get_task(database: Database, task_id: int) -> BackgroundTask:
    with database.session() as session:
        return BackgroundTaskRepository(session).require(task_id)


def test_startup_recovery_interrupts_only_abandoned_running_tasks(
    migrated_database: Database,
) -> None:
    running = add_task(
        migrated_database,
        "Running",
        status=BackgroundTaskStatus.RUNNING,
    )
    pending = add_task(
        migrated_database,
        "Pending",
        status=BackgroundTaskStatus.PENDING,
    )
    completed = add_task(
        migrated_database,
        "Completed",
        status=BackgroundTaskStatus.COMPLETED,
    )
    running_started_at = running.started_at

    recovered_ids = BackgroundTaskRecoveryService(migrated_database).recover_abandoned_tasks()

    interrupted = get_task(migrated_database, running.id)
    assert recovered_ids == (running.id,)
    assert interrupted.status is BackgroundTaskStatus.INTERRUPTED
    assert interrupted.started_at == running_started_at
    assert interrupted.completed_at is not None
    assert interrupted.error_message == INTERRUPTED_BY_WORKER_RESTART_MESSAGE
    assert get_task(migrated_database, pending.id).status is BackgroundTaskStatus.PENDING
    assert get_task(migrated_database, completed.id).status is BackgroundTaskStatus.COMPLETED


def test_startup_recovery_is_repeat_safe(migrated_database: Database) -> None:
    running = add_task(
        migrated_database,
        "Running",
        status=BackgroundTaskStatus.RUNNING,
    )
    service = BackgroundTaskRecoveryService(migrated_database)

    assert service.recover_abandoned_tasks() == (running.id,)
    first_recovery = get_task(migrated_database, running.id)
    assert service.recover_abandoned_tasks() == ()

    second_recovery = get_task(migrated_database, running.id)
    assert second_recovery.retry_count == 0
    assert second_recovery.completed_at == first_recovery.completed_at
    assert second_recovery.error_message == first_recovery.error_message


@pytest.mark.parametrize(
    "retryable_status",
    [BackgroundTaskStatus.FAILED, BackgroundTaskStatus.INTERRUPTED],
)
def test_explicit_retry_returns_retryable_task_to_pending_once(
    migrated_database: Database,
    retryable_status: BackgroundTaskStatus,
) -> None:
    task = add_task(
        migrated_database,
        retryable_status.value,
        status=(
            BackgroundTaskStatus.RUNNING
            if retryable_status is BackgroundTaskStatus.INTERRUPTED
            else retryable_status
        ),
    )
    service = BackgroundTaskRecoveryService(migrated_database)
    if retryable_status is BackgroundTaskStatus.INTERRUPTED:
        assert service.recover_abandoned_tasks() == (task.id,)

    result = service.retry_task(task.id)

    retried = get_task(migrated_database, task.id)
    assert result.task_id == task.id
    assert result.status is BackgroundTaskStatus.PENDING
    assert result.retry_count == 1
    assert retried.status is BackgroundTaskStatus.PENDING
    assert retried.retry_count == 1
    assert retried.started_at is None
    assert retried.completed_at is None
    assert retried.error_message is None

    with pytest.raises(InvalidBackgroundTaskTransitionError, match="PENDING to PENDING"):
        service.retry_task(task.id)
    assert get_task(migrated_database, task.id).retry_count == 1


@pytest.mark.parametrize(
    "status",
    [
        BackgroundTaskStatus.PENDING,
        BackgroundTaskStatus.RUNNING,
        BackgroundTaskStatus.COMPLETED,
    ],
)
def test_explicit_retry_rejects_non_retryable_task_states(
    migrated_database: Database,
    status: BackgroundTaskStatus,
) -> None:
    task = add_task(migrated_database, status.value, status=status)

    with pytest.raises(InvalidBackgroundTaskTransitionError):
        BackgroundTaskRecoveryService(migrated_database).retry_task(task.id)

    stored = get_task(migrated_database, task.id)
    assert stored.status is status
    assert stored.retry_count == 0
