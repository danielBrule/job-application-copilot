"""Transaction-owning use cases for the Background Runs screen."""

from job_application_copilot.domain import BackgroundRunFilters, BackgroundRunSummary
from job_application_copilot.repositories import BackgroundRunRepository, Database
from job_application_copilot.services.background_task_recovery import (
    BackgroundTaskRecoveryService,
    BackgroundTaskRetryResult,
)


class BackgroundRunService:
    """List durable task history and retry one eligible logical task."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, filters: BackgroundRunFilters | None = None) -> list[BackgroundRunSummary]:
        """Return monitoring rows matching the supplied exact filters."""

        with self.database.session() as session:
            return BackgroundRunRepository(session).list(filters)

    def failed_task_count(self) -> int:
        """Return retryable failed tasks requiring dashboard attention."""

        with self.database.session() as session:
            return BackgroundRunRepository(session).count_failed_tasks()

    def retry_task(self, task_id: int) -> BackgroundTaskRetryResult:
        """Return one failed or interrupted task to the worker queue."""

        return BackgroundTaskRecoveryService(self.database).retry_task(task_id)

    def retry_all_failed_tasks(self) -> tuple[BackgroundTaskRetryResult, ...]:
        """Return every currently failed task to the worker queue."""

        return BackgroundTaskRecoveryService(self.database).retry_all_failed_tasks()
