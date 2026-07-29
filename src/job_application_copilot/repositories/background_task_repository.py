"""Session-scoped persistence operations for background batches and tasks."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import (
    BackgroundOperation,
    BackgroundTaskStatus,
    is_valid_background_task_transition,
)
from job_application_copilot.errors import ApplicationNotFoundError, ApplicationValidationError
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask
from job_application_copilot.repositories.models.common import utc_now


class BackgroundBatchNotFoundError(ApplicationNotFoundError):
    """Raised when a required background batch does not exist."""

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        super().__init__(f"Background batch {batch_id} does not exist.")


class BackgroundTaskNotFoundError(ApplicationNotFoundError):
    """Raised when a required background task does not exist."""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"Background task {task_id} does not exist.")


class BackgroundTaskBatchOperationMismatchError(ApplicationValidationError):
    """Raised when task operation differs from its batch operation."""

    def __init__(
        self, batch_operation: BackgroundOperation, task_operation: BackgroundOperation
    ) -> None:
        super().__init__(
            "A background task operation must match its batch operation "
            f"({batch_operation.value} != {task_operation.value})."
        )


class InvalidBackgroundTaskTransitionError(ApplicationValidationError):
    """Raised for a lifecycle transition outside the permitted state graph."""

    def __init__(self, current: BackgroundTaskStatus, target: BackgroundTaskStatus) -> None:
        super().__init__(
            f"Background task cannot transition from {current.value} to {target.value}."
        )


class BackgroundBatchRepository:
    """Read and write background batches within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, batch: BackgroundBatch) -> BackgroundBatch:
        """Persist a new batch and populate generated values."""

        self.session.add(batch)
        self.session.flush()
        return batch

    def get(self, batch_id: int) -> BackgroundBatch | None:
        """Return a batch by identifier, or None when it does not exist."""

        return self.session.get(BackgroundBatch, batch_id)

    def require(self, batch_id: int) -> BackgroundBatch:
        """Return an existing batch or raise an actionable lookup error."""

        batch = self.get(batch_id)
        if batch is None:
            raise BackgroundBatchNotFoundError(batch_id)
        return batch


class BackgroundTaskRepository:
    """Read, create, and transition background tasks in one transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, task: BackgroundTask) -> BackgroundTask:
        """Persist a task after confirming it matches its canonical batch operation."""

        batch = BackgroundBatchRepository(self.session).require(task.batch_id)
        if task.operation is not batch.operation:
            raise BackgroundTaskBatchOperationMismatchError(batch.operation, task.operation)
        self.session.add(task)
        self.session.flush()
        return task

    def get(self, task_id: int) -> BackgroundTask | None:
        """Return a task by identifier, or None when it does not exist."""

        return self.session.get(BackgroundTask, task_id)

    def require(self, task_id: int) -> BackgroundTask:
        """Return an existing task or raise an actionable lookup error."""

        task = self.get(task_id)
        if task is None:
            raise BackgroundTaskNotFoundError(task_id)
        return task

    def list(
        self,
        *,
        batch_id: int | None = None,
        job_id: int | None = None,
        status: BackgroundTaskStatus | None = None,
    ) -> list[BackgroundTask]:
        """Return matching tasks in deterministic oldest-first queue order."""

        statement = select(BackgroundTask)
        if batch_id is not None:
            statement = statement.where(BackgroundTask.batch_id == batch_id)
        if job_id is not None:
            statement = statement.where(BackgroundTask.job_id == job_id)
        if status is not None:
            statement = statement.where(BackgroundTask.status == status)
        statement = statement.order_by(BackgroundTask.created_at.asc(), BackgroundTask.id.asc())
        return list(self.session.scalars(statement))

    def transition(
        self,
        task: BackgroundTask,
        target: BackgroundTaskStatus,
        *,
        error_message: str | None = None,
    ) -> BackgroundTask:
        """Apply one valid lifecycle transition and maintain its durable timestamps."""

        if not is_valid_background_task_transition(task.status, target):
            raise InvalidBackgroundTaskTransitionError(task.status, target)
        if error_message is not None and target not in {
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.INTERRUPTED,
        }:
            raise InvalidBackgroundTaskTransitionError(task.status, target)

        now = utc_now()
        if target is BackgroundTaskStatus.RUNNING:
            task.started_at = now
            task.completed_at = None
            task.error_message = None
        elif target in {BackgroundTaskStatus.FAILED, BackgroundTaskStatus.INTERRUPTED}:
            task.completed_at = now
            task.error_message = error_message
        elif target is BackgroundTaskStatus.COMPLETED:
            task.completed_at = now
            task.error_message = None
        elif target is BackgroundTaskStatus.PENDING:
            task.retry_count += 1
            task.started_at = None
            task.completed_at = None
            task.error_message = None

        task.status = target
        self.session.flush()
        return task
