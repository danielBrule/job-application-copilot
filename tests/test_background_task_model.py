"""Integration tests for background task persistence models and migration."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    Language,
    Location,
)
from job_application_copilot.repositories import Database, create_database
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


def make_job() -> Job:
    return Job(
        company="Example Ltd",
        job_title="Platform Engineer",
        location=Location.UK,
        language=Language.EN,
        source="LinkedIn",
        job_description="Build reliable systems.",
        date_added=date(2026, 7, 29),
    )


def test_creates_batch_and_task_with_defaults(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        job = make_job()
        session.add(job)
        session.flush()
        batch = BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        session.add(batch)
        session.flush()
        task = BackgroundTask(
            batch_id=batch.id,
            job_id=job.id,
            operation=BackgroundOperation.ASSESSMENT,
        )
        session.add(task)
        session.flush()

    assert batch.payload_metadata == {}
    assert task.status is BackgroundTaskStatus.PENDING
    assert task.retry_count == 0
    assert task.payload_metadata == {}
    assert task.created_at.microsecond == 0
    assert task.updated_at.microsecond == 0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("operation", "OTHER"),
        ("status", "QUEUED"),
        ("retry_count", -1),
    ],
)
def test_database_rejects_invalid_task_constraints(
    migrated_database: Database,
    column: str,
    value: str | int,
) -> None:
    with migrated_database.session() as session:
        job = make_job()
        session.add(job)
        session.flush()
        batch = BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        session.add(batch)
        session.flush()

    values: dict[str, object] = {
        "batch_id": batch.id,
        "job_id": job.id,
        "operation": "ASSESSMENT",
        "status": "PENDING",
        "retry_count": 0,
    }
    values[column] = value

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO background_tasks (
                        batch_id, job_id, operation, status, retry_count
                    )
                    VALUES (:batch_id, :job_id, :operation, :status, :retry_count)
                    """
                ),
                values,
            )


def test_database_allows_error_only_for_failed_or_interrupted_tasks(
    migrated_database: Database,
) -> None:
    with migrated_database.session() as session:
        job = make_job()
        session.add(job)
        session.flush()
        batch = BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        session.add(batch)
        session.flush()

    values = {
        "batch_id": batch.id,
        "job_id": job.id,
        "operation": "ASSESSMENT",
        "status": "PENDING",
        "error_message": "Unexpected error",
    }
    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            session.execute(BackgroundTask.__table__.insert().values(**values))


def test_job_delete_is_restricted_when_task_history_exists(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        job = make_job()
        session.add(job)
        session.flush()
        batch = BackgroundBatch(operation=BackgroundOperation.ASSESSMENT)
        session.add(batch)
        session.flush()
        session.add(
            BackgroundTask(
                batch_id=batch.id,
                job_id=job.id,
                operation=BackgroundOperation.ASSESSMENT,
            )
        )

    with pytest.raises(IntegrityError):
        with migrated_database.session() as session:
            stored = session.get(Job, job.id)
            assert stored is not None
            session.delete(stored)
            session.flush()


def test_migration_creates_background_task_schema(migrated_database: Database) -> None:
    inspector = inspect(migrated_database.engine)
    batch_columns = {column["name"] for column in inspector.get_columns("background_batches")}
    task_columns = {column["name"] for column in inspector.get_columns("background_tasks")}
    task_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("background_tasks")
    }

    assert batch_columns == {"id", "operation", "payload_metadata", "created_at"}
    assert task_columns == {
        "id",
        "batch_id",
        "job_id",
        "operation",
        "status",
        "retry_count",
        "payload_metadata",
        "pipeline_step",
        "started_at",
        "completed_at",
        "error_message",
        "created_at",
        "updated_at",
    }
    assert {
        "background_task_operation",
        "background_task_status",
        "ck_background_tasks_retry_count_non_negative",
        "ck_background_tasks_error_for_terminal_failure",
    } <= task_checks


def test_direct_insert_uses_task_defaults(migrated_database: Database) -> None:
    with migrated_database.session() as session:
        job = make_job()
        session.add(job)
        session.flush()
        batch_id = session.scalar(
            text("INSERT INTO background_batches (operation) VALUES ('ASSESSMENT') RETURNING id")
        )
        task_id = session.scalar(
            text(
                """
                INSERT INTO background_tasks (batch_id, job_id, operation)
                VALUES (:batch_id, :job_id, 'ASSESSMENT')
                RETURNING id
                """
            ),
            {"batch_id": batch_id, "job_id": job.id},
        )

    with migrated_database.session() as session:
        task = session.get(BackgroundTask, task_id)

    assert task is not None
    assert task.status is BackgroundTaskStatus.PENDING
    assert task.retry_count == 0
    assert task.payload_metadata == {}
