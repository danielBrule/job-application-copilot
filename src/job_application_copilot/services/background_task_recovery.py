"""Recovery and explicit retry use cases for durable background tasks."""

from dataclasses import dataclass

from job_application_copilot.domain import BackgroundTaskStatus
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.background_task_repository import (
    BackgroundTaskRepository,
)

INTERRUPTED_BY_WORKER_RESTART_MESSAGE = (
    "Worker startup found this task still RUNNING after the previous worker stopped "
    "before recording completion."
)


@dataclass(frozen=True, slots=True)
class BackgroundTaskRetryResult:
    """Durable state returned after one explicit retry request."""

    task_id: int
    retry_count: int
    status: BackgroundTaskStatus


class BackgroundTaskRecoveryService:
    """Recover abandoned work and expose the guarded manual retry operation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def recover_abandoned_tasks(self) -> tuple[int, ...]:
        """Mark every task left RUNNING by the previous worker as INTERRUPTED."""

        with self.database.session() as session:
            tasks = BackgroundTaskRepository(session)
            abandoned_tasks = tasks.list(status=BackgroundTaskStatus.RUNNING)
            recovered_ids: list[int] = []
            for task in abandoned_tasks:
                tasks.transition(
                    task,
                    BackgroundTaskStatus.INTERRUPTED,
                    error_message=INTERRUPTED_BY_WORKER_RESTART_MESSAGE,
                )
                recovered_ids.append(task.id)
            return tuple(recovered_ids)

    def retry_task(self, task_id: int) -> BackgroundTaskRetryResult:
        """Return one failed or interrupted task to PENDING exactly once."""

        with self.database.session() as session:
            tasks = BackgroundTaskRepository(session)
            task = tasks.require(task_id)
            tasks.transition(task, BackgroundTaskStatus.PENDING)
            return BackgroundTaskRetryResult(
                task_id=task.id,
                retry_count=task.retry_count,
                status=task.status,
            )

    def retry_all_failed_tasks(self) -> tuple[BackgroundTaskRetryResult, ...]:
        """Return every currently failed task to PENDING in one transaction."""

        with self.database.session() as session:
            tasks = BackgroundTaskRepository(session)
            failed_tasks = tasks.list(status=BackgroundTaskStatus.FAILED)
            results: list[BackgroundTaskRetryResult] = []
            for task in failed_tasks:
                retried = tasks.transition(task, BackgroundTaskStatus.PENDING)
                results.append(
                    BackgroundTaskRetryResult(
                        task_id=retried.id,
                        retry_count=retried.retry_count,
                        status=retried.status,
                    )
                )
            return tuple(results)
