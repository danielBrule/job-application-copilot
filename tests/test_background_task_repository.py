"""Integration tests for background batch and task repositories."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.repositories import (
    BackgroundBatchRepository,
    BackgroundTaskBatchOperationMismatchError,
    BackgroundTaskRepository,
    Database,
    InvalidBackgroundTaskTransitionError,
    create_database,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask, Job
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


def add_job(session: Session, company: str) -> Job:
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
    return job


def test_creates_and_queries_batch_tasks_deterministically(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        first_job = add_job(session, "First")
        second_job = add_job(session, "Second")
        batches = BackgroundBatchRepository(session)
        tasks = BackgroundTaskRepository(session)
        batch = batches.add(
            BackgroundBatch(
                operation=BackgroundOperation.ASSESSMENT,
                payload_metadata={"requested_from": "job list"},
            )
        )
        first_task = tasks.add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=first_job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )
        second_task = tasks.add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=second_job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )

        assert [task.id for task in tasks.list(batch_id=batch.id)] == [
            first_task.id,
            second_task.id,
        ]
        assert tasks.list(job_id=first_job.id) == [first_task]
        assert tasks.list(status=BackgroundTaskStatus.PENDING) == [first_task, second_task]


def test_rejects_task_with_operation_different_from_its_batch(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job = add_job(session, "Example")
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )

        with pytest.raises(BackgroundTaskBatchOperationMismatchError):
            BackgroundTaskRepository(session).add(
                BackgroundTask(
                    batch_id=batch.id,
                    job_id=job.id,
                    operation=BackgroundOperation.CV_GENERATION,
                )
            )


def test_transitions_task_and_retries_failed_or_interrupted_work(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job = add_job(session, "Example")
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.CV_GENERATION)
        )
        tasks = BackgroundTaskRepository(session)
        task = tasks.add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job.id,
                operation=BackgroundOperation.CV_GENERATION,
            )
        )

        tasks.transition(task, BackgroundTaskStatus.RUNNING)
        started_at = task.started_at
        tasks.transition(
            task,
            BackgroundTaskStatus.FAILED,
            error_message="The model request timed out.",
        )
        assert task.completed_at is not None
        assert task.error_message == "The model request timed out."

        tasks.transition(task, BackgroundTaskStatus.PENDING)

    assert started_at is not None
    assert task.status is BackgroundTaskStatus.PENDING
    assert task.retry_count == 1
    assert task.started_at is None
    assert task.completed_at is None
    assert task.error_message is None


def test_rejects_invalid_state_transition(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        job = add_job(session, "Example")
        batch = BackgroundBatchRepository(session).add(
            BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        )
        tasks = BackgroundTaskRepository(session)
        task = tasks.add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )

        with pytest.raises(InvalidBackgroundTaskTransitionError, match="PENDING to COMPLETED"):
            tasks.transition(task, BackgroundTaskStatus.COMPLETED)
