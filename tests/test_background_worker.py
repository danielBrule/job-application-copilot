"""Integration tests for the sequential local background worker."""

from datetime import date
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

import job_application_copilot.services.background_worker as background_worker_module
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
    create_database,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask, Job
from job_application_copilot.services.background_worker import (
    BackgroundWorker,
    BackgroundWorkerAlreadyRunningError,
    BackgroundWorkerLease,
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


def add_task(database: Database, company: str, operation: BackgroundOperation) -> BackgroundTask:
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
        batch = BackgroundBatchRepository(session).add(BackgroundBatch(operation=operation))
        return BackgroundTaskRepository(session).add(
            BackgroundTask(batch_id=batch.id, job_id=job.id, operation=operation)
        )


def get_task(database: Database, task_id: int) -> BackgroundTask:
    with database.session() as session:
        task = BackgroundTaskRepository(session).get(task_id)
        assert task is not None
        return task


def test_processes_dummy_tasks_sequentially_in_oldest_first_order(
    migrated_database: Database,
) -> None:
    first = add_task(migrated_database, "First", BackgroundOperation.ASSESSMENT)
    second = add_task(migrated_database, "Second", BackgroundOperation.ASSESSMENT)
    processed_ids: list[int] = []
    worker = BackgroundWorker(
        migrated_database,
        {BackgroundOperation.ASSESSMENT: lambda task: processed_ids.append(task.id)},
    )

    assert worker.process_next_task()
    assert worker.process_next_task()
    assert not worker.process_next_task()

    assert processed_ids == [first.id, second.id]
    assert get_task(migrated_database, first.id).status is BackgroundTaskStatus.COMPLETED
    assert get_task(migrated_database, second.id).status is BackgroundTaskStatus.COMPLETED


def test_handler_failure_marks_only_its_task_failed_and_continues(
    migrated_database: Database,
) -> None:
    failed = add_task(migrated_database, "Failure", BackgroundOperation.ASSESSMENT)
    completed = add_task(migrated_database, "Success", BackgroundOperation.ASSESSMENT)
    call_count = 0

    def handler(task: BackgroundTask) -> None:
        nonlocal call_count
        call_count += 1
        if task.id == failed.id:
            raise RuntimeError("private handler detail")

    worker = BackgroundWorker(migrated_database, {BackgroundOperation.ASSESSMENT: handler})

    assert worker.process_next_task()
    assert worker.process_next_task()

    failed_task = get_task(migrated_database, failed.id)
    completed_task = get_task(migrated_database, completed.id)
    assert call_count == 2
    assert failed_task.status is BackgroundTaskStatus.FAILED
    assert failed_task.error_message == "Task handler failed; see the private worker log."
    assert "private handler detail" not in failed_task.error_message
    assert completed_task.status is BackgroundTaskStatus.COMPLETED


def test_leaves_pending_tasks_for_unregistered_operations_untouched(
    migrated_database: Database,
) -> None:
    task = add_task(migrated_database, "CV", BackgroundOperation.CV_GENERATION)
    worker = BackgroundWorker(
        migrated_database, {BackgroundOperation.ASSESSMENT: lambda task: None}
    )

    assert not worker.process_next_task()

    assert get_task(migrated_database, task.id).status is BackgroundTaskStatus.PENDING


def test_clean_shutdown_finishes_current_task_without_claiming_another(
    migrated_database: Database,
) -> None:
    first = add_task(migrated_database, "First", BackgroundOperation.ASSESSMENT)
    second = add_task(migrated_database, "Second", BackgroundOperation.ASSESSMENT)
    worker: BackgroundWorker

    def handler(task: BackgroundTask) -> None:
        assert task.id == first.id
        worker.request_stop()

    worker = BackgroundWorker(migrated_database, {BackgroundOperation.ASSESSMENT: handler})
    worker.run()

    assert get_task(migrated_database, first.id).status is BackgroundTaskStatus.COMPLETED
    assert get_task(migrated_database, second.id).status is BackgroundTaskStatus.PENDING


def test_idle_worker_checks_external_stop_request_without_waiting_a_minute(
    migrated_database: Database,
) -> None:
    stop_requested = Event()
    worker = BackgroundWorker(
        migrated_database,
        handlers={},
        idle_poll_interval_seconds=60,
        stop_requested=stop_requested.is_set,
    )
    stop_requested.set()

    worker.run()


def test_worker_lease_rejects_second_live_worker_and_releases_cleanly(tmp_path: Path) -> None:
    lease_path = tmp_path / "worker.lock"
    first_lease = BackgroundWorkerLease(lease_path)
    first_lease.acquire()

    with pytest.raises(BackgroundWorkerAlreadyRunningError):
        BackgroundWorkerLease(lease_path).acquire()

    first_lease.release()
    assert not lease_path.exists()


def test_worker_lease_replaces_stale_crash_artifact(tmp_path: Path) -> None:
    lease_path = tmp_path / "worker.lock"
    lease_path.write_text(
        '{"process_id": 0, "token": "stale", "started_at": "old", "heartbeat_at": "old"}',
        encoding="utf-8",
    )
    lease = BackgroundWorkerLease(lease_path)

    lease.acquire()

    assert '"process_id": ' in lease_path.read_text(encoding="utf-8")
    assert '"token": "stale"' not in lease_path.read_text(encoding="utf-8")
    lease.release()


def test_windows_process_probe_never_uses_os_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    windows_probe = Mock(return_value=True)
    os_kill = Mock(side_effect=AssertionError("os.kill must not probe Windows processes"))
    monkeypatch.setattr(background_worker_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(background_worker_module, "_windows_process_is_alive", windows_probe)
    monkeypatch.setattr(background_worker_module.os, "kill", os_kill)

    assert background_worker_module._process_is_alive(123)
    windows_probe.assert_called_once_with(123)
    os_kill.assert_not_called()
